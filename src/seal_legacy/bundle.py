"""Portable verifier bundle creation from saved mechanical evidence.

The bundle writer does not rerun checks, decide a verdict, call an LLM, append
a ledger, or update Task completion.  It packages one already-recorded Task/run
pair so an independent verifier can inspect a bounded set of evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any

from ._source_binding_documents import (
    SOURCE_AFTER_CHECKS_FILENAME,
    SOURCE_BEFORE_CHECKS_FILENAME,
)
from .exit_codes import ExitCode
from .run_validator import (
    RunEvidenceError,
    RunIdentityError,
    RunValidationError,
    ValidatedRun,
    validate_run,
)
from .source_snapshot import SourceSnapshot
from .task import TaskError


BUNDLE_SCHEMA_VERSION = 1


class BundleError(TaskError):
    """Base error for verifier bundle creation."""


class BundleInputError(BundleError):
    """Raised when a bundle request or Task/run identity is invalid."""

    exit_code = ExitCode.INVALID_INPUT_OR_SCHEMA


class BundleEvidenceError(BundleError):
    """Raised when saved evidence is missing, corrupt, or unsafe to package."""

    exit_code = ExitCode.EVIDENCE_MISSING_OR_CORRUPT


@dataclass(frozen=True)
class VerificationBundle:
    """Metadata for one completed bundle export."""

    task_id: str
    run_id: str
    bundle_path: Path
    manifest_path: Path
    manifest: dict[str, Any]


def create_verification_bundle(
    task_id: str,
    run_id: str,
    output: str | Path,
    *,
    cwd: str | Path | None = None,
) -> VerificationBundle:
    """Create an atomic, portable verifier bundle for one saved Task/run.

    Only the selected run's required evidence, check logs referenced by that
    evidence, and the installed package's verifier instructions are copied.
    Repository source files, arbitrary ignored files, process environment data,
    completion records, and verifier verdicts are deliberately outside this
    operation.
    """
    try:
        validated_run = validate_run(task_id, run_id, cwd=cwd)
    except RunIdentityError as error:
        raise BundleInputError(str(error)) from error
    except RunValidationError as error:
        raise BundleEvidenceError(str(error)) from error

    output_path = _resolve_output_path(output, validated_run.repository)
    _validate_output_path(output_path, validated_run.evidence_path)
    bundle_changed_files = _bundle_changed_files(validated_run)
    changes = bundle_changed_files["changes"]
    assert isinstance(changes, list)  # Guaranteed by validate_run().
    _reject_gitignored_changes(validated_run.repository, changes)
    prompt = _read_verifier_instructions()
    payloads = _bundle_payloads(
        repository=validated_run.repository,
        task=validated_run.task,
        changed_files=bundle_changed_files,
        checks_document=validated_run.checks,
        verification=validated_run.verification,
        diff_patch=validated_run.diff_patch,
        validated_run=validated_run,
        source_before_checks=validated_run.source_before_checks,
        source_after_checks=validated_run.source_after_checks,
        prompt=prompt,
    )
    temporary_path = _create_temporary_output_directory(output_path)
    try:
        for relative_path, contents in payloads.items():
            destination = temporary_path.joinpath(*PurePosixPath(relative_path).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contents)

        manifest = _build_manifest(
            task_id,
            run_id,
            payloads,
            source_evidence_sha256=validated_run.evidence_sha256,
        )
        manifest_path = temporary_path / "manifest.json"
        manifest_path.write_bytes(_pretty_json_bytes(manifest))
        os.replace(temporary_path, output_path)
    except BaseException:
        shutil.rmtree(temporary_path, ignore_errors=True)
        raise

    return VerificationBundle(
        task_id=task_id,
        run_id=run_id,
        bundle_path=output_path,
        manifest_path=output_path / "manifest.json",
        manifest=manifest,
    )


def _reject_gitignored_changes(repository: Path, changes: list[object]) -> None:
    for index, change in enumerate(changes):
        if not isinstance(change, Mapping):
            raise BundleEvidenceError(f"changed-files.json change at index {index} is invalid.")
        for field in ("path", "previous_path"):
            value = change.get(field)
            if value is None and field == "previous_path":
                continue
            if not isinstance(value, str) or not value:
                raise BundleEvidenceError(
                    f"changed-files.json change at index {index} has an invalid {field}."
                )
            if _is_gitignored(repository, value):
                raise BundleEvidenceError(
                    f"changed-files.json includes gitignored path '{value}'."
                )


def _bundle_changed_files(validated_run: ValidatedRun) -> dict[str, Any]:
    """Select product changes already verified by the canonical validator."""
    changes = validated_run.verification["changed_files"]
    assert isinstance(changes, list)  # Guaranteed by validate_run().
    return {
        **validated_run.changed_files,
        "changes": [dict(change) for change in changes],
    }


def _is_gitignored(repository: Path, relative_path: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), "check-ignore", "-q", "--", relative_path],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as error:
        raise BundleEvidenceError("Git is required to validate bundle paths.") from error
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    detail = result.stderr.strip()
    raise BundleEvidenceError(detail or "Git could not evaluate ignored bundle paths.")


def _bundle_payloads(
    *,
    repository: Path,
    task: Mapping[str, Any],
    changed_files: Mapping[str, Any],
    checks_document: Mapping[str, Any],
    verification: Mapping[str, Any],
    diff_patch: bytes,
    validated_run: ValidatedRun,
    source_before_checks: SourceSnapshot,
    source_after_checks: SourceSnapshot,
    prompt: str,
) -> dict[str, bytes]:
    replacements = _path_replacements(repository)
    payloads = {
        "task.json": _pretty_json_bytes(_sanitize_value(task, replacements)),
        "changed-files.json": _pretty_json_bytes(
            _sanitize_value(changed_files, replacements)
        ),
        "checks.json": _pretty_json_bytes(_sanitize_value(checks_document, replacements)),
        "verification.json": _pretty_json_bytes(
            _sanitize_value(verification, replacements)
        ),
        "diff.patch": _sanitize_bytes(diff_patch, replacements),
        "verifier.md": prompt.encode("utf-8"),
    }
    payloads[SOURCE_BEFORE_CHECKS_FILENAME] = _pretty_json_bytes(
        source_before_checks.to_document()
    )
    payloads[SOURCE_AFTER_CHECKS_FILENAME] = _pretty_json_bytes(
        source_after_checks.to_document()
    )
    for relative_path in validated_run.log_paths:
        payloads[relative_path.as_posix()] = _sanitize_bytes(
            _read_validated_log_bytes(validated_run, relative_path),
            replacements,
        )
    payloads = dict(sorted(payloads.items()))
    for path, contents in payloads.items():
        if _sanitize_bytes(contents, replacements) != contents:
            raise BundleEvidenceError(
                f"Bundle payload '{path}' still contains a known local path."
            )
    return payloads


def _build_manifest(
    task_id: str,
    run_id: str,
    payloads: Mapping[str, bytes],
    *,
    source_evidence_sha256: str,
) -> dict[str, Any]:
    files = [
        {
            "path": path,
            "sha256": hashlib.sha256(contents).hexdigest(),
            "size_bytes": len(contents),
        }
        for path, contents in sorted(payloads.items())
    ]
    manifest_without_hash: dict[str, Any] = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "task_id": task_id,
        "run_id": run_id,
        "source_evidence_sha256": source_evidence_sha256,
        "created_at": _utc_timestamp(),
        "files": files,
        "total_size_bytes": sum(entry["size_bytes"] for entry in files),
    }
    return {
        **manifest_without_hash,
        "bundle_sha256": hashlib.sha256(
            _canonical_json_bytes(manifest_without_hash)
        ).hexdigest(),
    }


def _read_verifier_instructions() -> str:
    """Read the installed package's versioned verifier instruction resource."""
    try:
        return (
            resources.files("seal_legacy")
            .joinpath("resources", "verifier.md")
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError, UnicodeDecodeError) as error:
        raise BundleEvidenceError("Verifier instructions are missing or unreadable.") from error


def _read_validated_log_bytes(
    validated_run: ValidatedRun,
    relative_path: PurePosixPath,
) -> bytes:
    """Read a log path returned by ``validate_run`` without revalidating the Run."""
    try:
        return validated_run.read_log_bytes(relative_path)
    except RunEvidenceError as error:
        raise BundleEvidenceError(
            f"Could not read previously validated log file: {relative_path.as_posix()}."
        ) from error


def _resolve_output_path(output: str | Path, repository: Path) -> Path:
    path = Path(output)
    return path.resolve() if path.is_absolute() else (repository / path).resolve()


def _validate_output_path(output_path: Path, evidence_path: Path) -> None:
    if output_path.exists():
        raise BundleInputError("Bundle output directory must not already exist.")
    evidence_root = evidence_path.resolve()
    if output_path.is_relative_to(evidence_root):
        raise BundleInputError("Bundle output directory cannot be inside source evidence.")


def _create_temporary_output_directory(output_path: Path) -> Path:
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return Path(
            tempfile.mkdtemp(prefix=f".{output_path.name}.", dir=output_path.parent)
        )
    except OSError as error:
        raise BundleInputError("Could not create the bundle output directory.") from error


def _sanitize_value(value: object, replacements: tuple[tuple[str, str], ...]) -> object:
    if isinstance(value, str):
        return _sanitize_text(value, replacements)
    if isinstance(value, Mapping):
        return {
            _sanitize_text(str(key), replacements): _sanitize_value(item, replacements)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item, replacements) for item in value]
    return value


def _sanitize_bytes(contents: bytes, replacements: tuple[tuple[str, str], ...]) -> bytes:
    result = contents
    for spelling, replacement in replacements:
        pattern = rb"(?<![A-Za-z0-9_.-])" + re.escape(os.fsencode(spelling)) + rb"(?![A-Za-z0-9_.-])"
        result = re.sub(pattern, replacement.encode("ascii"), result)
    return result


def _sanitize_text(value: str, replacements: tuple[tuple[str, str], ...]) -> str:
    result = value
    for spelling, replacement in replacements:
        pattern = r"(?<![\w.-])" + re.escape(spelling) + r"(?![\w.-])"
        result = re.sub(pattern, replacement, result)
    return result


def _path_replacements(repository: Path) -> tuple[tuple[str, str], ...]:
    roots = ((repository, "."), (Path.home(), "<HOME>"))
    replacements = ((spelling, replacement) for root, replacement in roots
                    for spelling in _path_spellings(root))
    return tuple(sorted(replacements, key=lambda item: len(item[0]), reverse=True))


def _path_spellings(path: Path) -> set[str]:
    spellings = {str(path), str(path.resolve())}
    for spelling in tuple(spellings):
        if spelling.startswith("/private/"):
            spellings.add(spelling.removeprefix("/private"))
        elif spelling.startswith("/var/"):
            spellings.add("/private" + spelling)
        spellings.add(spelling.replace("/", "\\"))
    return spellings


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _pretty_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8", "backslashreplace"
    )


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
