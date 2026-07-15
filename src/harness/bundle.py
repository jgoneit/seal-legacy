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
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .exit_codes import ExitCode
from .gitdiff import find_repository_root, is_harness_metadata_path
from .task import TaskError, show_task, validate_task_id


BUNDLE_SCHEMA_VERSION = 1
_VERIFICATION_SCHEMA_VERSION = 1
_REQUIRED_EVIDENCE_FILES = (
    "task.json",
    "changed-files.json",
    "diff.patch",
    "checks.json",
    "verification.json",
)
_RUN_ID_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)
_POSIX_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9_.-])/(?:[^\s\x00\"'<>|/]+(?:/[^\s\x00\"'<>|/]+)*)"
)
_WINDOWS_ABSOLUTE_PATH = re.compile(
    r"(?i)(?<![A-Z0-9_])[A-Z]:[\\/][^\s\x00\"'<>|]*"
)
_UNC_PATH = re.compile(r"(?<!\\)\\\\[^\s\\/\x00\"'<>|]+(?:\\[^\s\x00\"'<>|]+)+")


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
    evidence, and the repository verifier instructions are copied.  Repository
    source files, arbitrary ignored files, process environment data, completion
    records, and verifier verdicts are deliberately outside this operation.
    """
    validate_task_id(task_id)
    _validate_run_id(run_id)
    repository = find_repository_root(cwd)
    task = show_task(task_id, cwd=repository)
    evidence_path = repository / ".harness" / "evidence" / task_id / run_id
    output_path = _resolve_output_path(output, repository)
    _validate_output_path(output_path, evidence_path)

    evidence_task = _read_evidence_json(evidence_path, "task.json")
    changed_files = _read_evidence_json(evidence_path, "changed-files.json")
    checks_document = _read_evidence_json(evidence_path, "checks.json")
    verification = _read_evidence_json(evidence_path, "verification.json")
    diff_patch = _read_evidence_bytes(evidence_path, PurePosixPath("diff.patch"))

    bundle_changed_files = _product_changed_files(changed_files)
    log_paths = _validate_evidence(
        repository=repository,
        task_id=task_id,
        run_id=run_id,
        task=task,
        evidence_task=evidence_task,
        changed_files=bundle_changed_files,
        checks_document=checks_document,
        verification=verification,
        evidence_path=evidence_path,
    )
    prompt = _read_verifier_instructions(repository)
    payloads = _bundle_payloads(
        repository=repository,
        evidence_task=evidence_task,
        changed_files=bundle_changed_files,
        checks_document=checks_document,
        verification=verification,
        diff_patch=diff_patch,
        log_paths=log_paths,
        evidence_path=evidence_path,
        prompt=prompt,
    )
    _assert_payloads_are_portable(payloads)

    temporary_path = _create_temporary_output_directory(output_path)
    try:
        for relative_path, contents in payloads.items():
            destination = temporary_path.joinpath(*PurePosixPath(relative_path).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contents)

        manifest = _build_manifest(task_id, run_id, payloads)
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


def _validate_evidence(
    *,
    repository: Path,
    task_id: str,
    run_id: str,
    task: Mapping[str, Any],
    evidence_task: Mapping[str, Any],
    changed_files: Mapping[str, Any],
    checks_document: Mapping[str, Any],
    verification: Mapping[str, Any],
    evidence_path: Path,
) -> list[PurePosixPath]:
    for filename, document in (
        ("task.json", evidence_task),
        ("changed-files.json", changed_files),
        ("checks.json", checks_document),
        ("verification.json", verification),
    ):
        if document.get("schema_version") != _VERIFICATION_SCHEMA_VERSION:
            raise BundleEvidenceError(
                f"Evidence file '{filename}' has an unsupported schema_version."
            )

    listed_files = _listed_evidence_files(evidence_path, verification)
    if evidence_task != task:
        raise BundleInputError(
            f"Evidence task snapshot does not match saved Task '{task_id}'."
        )

    recorded_task_id = _required_string(verification, "task_id", "verification.json")
    recorded_run_id = _required_string(verification, "run_id", "verification.json")
    if recorded_task_id != task_id or recorded_run_id != run_id:
        raise BundleInputError(
            "Evidence task/run identity does not match the requested Task and run id."
        )

    changed = changed_files.get("changes")
    if not isinstance(changed, list):
        raise BundleEvidenceError("changed-files.json changes must be an array.")
    _reject_gitignored_changes(repository, changed)

    records, log_paths = _validate_check_records(task, checks_document, listed_files)
    scope_pass = _required_boolean(verification, "scope_pass", "verification.json")
    required_checks_pass = _required_boolean(
        verification, "required_checks_pass", "verification.json"
    )
    mechanical_result = _required_string(
        verification, "mechanical_result", "verification.json"
    )
    if mechanical_result not in {"pass", "fail"}:
        raise BundleEvidenceError(
            "verification.json mechanical_result must be 'pass' or 'fail'."
        )

    computed_required_checks_pass = all(
        bool(record["passed"]) for record in records if bool(record["required"])
    )
    expected_result = "pass" if scope_pass and computed_required_checks_pass else "fail"
    if required_checks_pass != computed_required_checks_pass:
        raise BundleEvidenceError(
            "verification.json required_checks_pass does not match checks.json."
        )
    if mechanical_result != expected_result:
        raise BundleEvidenceError(
            "verification.json mechanical_result does not match its saved evidence."
        )
    return log_paths


def _listed_evidence_files(
    evidence_path: Path, verification: Mapping[str, Any]
) -> set[str]:
    raw_files = verification.get("evidence_files")
    if not isinstance(raw_files, list) or not raw_files:
        raise BundleEvidenceError(
            "verification.json evidence_files must be a non-empty array."
        )

    listed_files: set[str] = set()
    for index, value in enumerate(raw_files):
        if not isinstance(value, str) or not value:
            raise BundleEvidenceError(
                f"verification.json evidence_files[{index}] must be a non-empty string."
            )
        relative_path = _safe_evidence_relative_path(value)
        normalized = relative_path.as_posix()
        if normalized in listed_files:
            raise BundleEvidenceError(
                f"verification.json lists evidence file '{normalized}' more than once."
            )
        listed_files.add(normalized)
        _read_evidence_bytes(evidence_path, relative_path)

    missing = set(_REQUIRED_EVIDENCE_FILES) - listed_files
    if missing:
        names = ", ".join(sorted(missing))
        raise BundleEvidenceError(
            f"verification.json evidence_files is missing required entry(s): {names}."
        )
    return listed_files


def _validate_check_records(
    task: Mapping[str, Any],
    checks_document: Mapping[str, Any],
    listed_files: set[str],
) -> tuple[list[dict[str, Any]], list[PurePosixPath]]:
    task_checks = task.get("checks")
    recorded_checks = checks_document.get("checks")
    if not isinstance(task_checks, list):
        raise BundleInputError("Saved Task snapshot checks must be an array.")
    if not isinstance(recorded_checks, list) or len(recorded_checks) != len(task_checks):
        raise BundleEvidenceError(
            "checks.json does not contain one result for every Task check."
        )

    records: list[dict[str, Any]] = []
    log_paths: list[PurePosixPath] = []
    seen_logs: set[str] = set()
    for index, (task_check, recorded_check) in enumerate(zip(task_checks, recorded_checks)):
        if not isinstance(task_check, Mapping):
            raise BundleInputError(f"Saved Task check at index {index} is invalid.")
        if not isinstance(recorded_check, Mapping):
            raise BundleEvidenceError(f"checks.json check at index {index} is invalid.")

        expected_name = task_check.get("name")
        expected_argv = task_check.get("argv")
        expected_required = task_check.get("required")
        record = dict(recorded_check)
        if (
            not isinstance(expected_name, str)
            or not isinstance(expected_argv, list)
            or type(expected_required) is not bool
            or record.get("name") != expected_name
            or record.get("argv") != expected_argv
            or record.get("required") is not expected_required
        ):
            raise BundleEvidenceError(
                f"checks.json check at index {index} does not match the saved Task."
            )

        passed = record.get("passed")
        timed_out = record.get("timed_out")
        exit_code = record.get("exit_code")
        if type(passed) is not bool or type(timed_out) is not bool:
            raise BundleEvidenceError(
                f"checks.json check at index {index} is missing pass/timeout state."
            )
        if exit_code is not None and type(exit_code) is not int:
            raise BundleEvidenceError(
                f"checks.json check at index {index} has an invalid exit code."
            )
        if passed != (not timed_out and exit_code == 0):
            raise BundleEvidenceError(
                f"checks.json check at index {index} pass state does not match its exit code."
            )

        for field in ("stdout_path", "stderr_path"):
            value = record.get(field)
            if not isinstance(value, str) or not value:
                raise BundleEvidenceError(
                    f"checks.json check at index {index} is missing {field}."
                )
            relative_path = _safe_evidence_relative_path(value)
            normalized = relative_path.as_posix()
            if normalized not in listed_files:
                raise BundleEvidenceError(
                    f"checks.json check at index {index} {field} is not listed in verification.json."
                )
            if normalized not in seen_logs:
                seen_logs.add(normalized)
                log_paths.append(relative_path)
        records.append(record)
    return records, log_paths


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
            relative_path = _safe_repository_relative_path(value)
            if _is_gitignored(repository, relative_path):
                raise BundleEvidenceError(
                    f"changed-files.json includes gitignored path '{relative_path}'."
                )


def _product_changed_files(document: Mapping[str, Any]) -> dict[str, Any]:
    changes = document.get("changes")
    if not isinstance(changes, list):
        raise BundleEvidenceError("changed-files.json changes must be an array.")

    product_changes: list[dict[str, Any]] = []
    for index, change in enumerate(changes):
        if not isinstance(change, Mapping):
            raise BundleEvidenceError(f"changed-files.json change at index {index} is invalid.")
        path = change.get("path")
        previous_path = change.get("previous_path")
        if not isinstance(path, str) or not path:
            raise BundleEvidenceError(
                f"changed-files.json change at index {index} has an invalid path."
            )
        if previous_path is not None and not isinstance(previous_path, str):
            raise BundleEvidenceError(
                f"changed-files.json change at index {index} has an invalid previous_path."
            )
        if is_harness_metadata_path(path) or (
            isinstance(previous_path, str) and is_harness_metadata_path(previous_path)
        ):
            continue
        product_changes.append(dict(change))
    return {**dict(document), "changes": product_changes}


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
    evidence_task: Mapping[str, Any],
    changed_files: Mapping[str, Any],
    checks_document: Mapping[str, Any],
    verification: Mapping[str, Any],
    diff_patch: bytes,
    log_paths: list[PurePosixPath],
    evidence_path: Path,
    prompt: str,
) -> dict[str, bytes]:
    payloads = {
        "task.json": _pretty_json_bytes(_sanitize_value(evidence_task, repository)),
        "changed-files.json": _pretty_json_bytes(_sanitize_value(changed_files, repository)),
        "checks.json": _pretty_json_bytes(_sanitize_value(checks_document, repository)),
        "verification.json": _pretty_json_bytes(_sanitize_value(verification, repository)),
        "diff.patch": _sanitize_bytes(diff_patch, repository),
        "verifier.md": prompt.encode("utf-8"),
    }
    for relative_path in log_paths:
        payloads[relative_path.as_posix()] = _sanitize_bytes(
            _read_evidence_bytes(evidence_path, relative_path), repository
        )
    return dict(sorted(payloads.items()))


def _build_manifest(task_id: str, run_id: str, payloads: Mapping[str, bytes]) -> dict[str, Any]:
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


def _read_verifier_instructions(repository: Path) -> str:
    path = repository / "prompts" / "verifier.md"
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise BundleEvidenceError("Verifier instructions are missing or unreadable.") from error


def _read_evidence_json(evidence_path: Path, filename: str) -> dict[str, Any]:
    relative_path = _safe_evidence_relative_path(filename)
    try:
        document = json.loads(_read_evidence_bytes(evidence_path, relative_path))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BundleEvidenceError(f"Evidence file '{filename}' is not valid JSON.") from error
    if not isinstance(document, Mapping):
        raise BundleEvidenceError(f"Evidence file '{filename}' must be a JSON object.")
    return dict(document)


def _read_evidence_bytes(evidence_path: Path, relative_path: PurePosixPath) -> bytes:
    root = evidence_path.resolve()
    candidate = evidence_path.joinpath(*relative_path.parts)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise BundleEvidenceError(
            f"Required evidence file is missing: {relative_path.as_posix()}."
        ) from error
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise BundleEvidenceError(
            f"Required evidence file is unsafe or missing: {relative_path.as_posix()}."
        )
    try:
        return resolved.read_bytes()
    except OSError as error:
        raise BundleEvidenceError(
            f"Could not read evidence file: {relative_path.as_posix()}."
        ) from error


def _safe_evidence_relative_path(value: str) -> PurePosixPath:
    if "\\" in value:
        raise BundleEvidenceError("Evidence file paths must use relative POSIX paths.")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise BundleEvidenceError("Evidence file paths must stay inside the run directory.")
    return path


def _safe_repository_relative_path(value: str) -> str:
    portable = value.replace("\\", "/")
    windows_path = PureWindowsPath(value)
    path = PurePosixPath(portable)
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise BundleEvidenceError("Changed file paths must be repository-relative.")
    return path.as_posix()


def _required_string(document: Mapping[str, Any], field: str, filename: str) -> str:
    value = document.get(field)
    if not isinstance(value, str) or not value:
        raise BundleEvidenceError(
            f"Evidence file '{filename}' field '{field}' must be a non-empty string."
        )
    return value


def _required_boolean(document: Mapping[str, Any], field: str, filename: str) -> bool:
    value = document.get(field)
    if type(value) is not bool:
        raise BundleEvidenceError(
            f"Evidence file '{filename}' field '{field}' must be a boolean."
        )
    return value


def _validate_run_id(run_id: object) -> str:
    if not isinstance(run_id, str) or not run_id:
        raise BundleInputError("Run id must be a non-empty string.")
    if run_id[0] not in _RUN_ID_CHARACTERS - {"_", "-"} or any(
        character not in _RUN_ID_CHARACTERS for character in run_id
    ):
        raise BundleInputError(
            "Run id must begin with an alphanumeric character and contain only "
            "letters, numbers, underscores, or hyphens."
        )
    return run_id


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


def _sanitize_value(value: object, repository: Path) -> object:
    if isinstance(value, str):
        return _sanitize_text(value, repository)
    if isinstance(value, Mapping):
        return {
            _sanitize_text(str(key), repository): _sanitize_value(item, repository)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item, repository) for item in value]
    return value


def _sanitize_bytes(contents: bytes, repository: Path) -> bytes:
    return _sanitize_text(contents.decode("utf-8", "replace"), repository).encode("utf-8")


def _sanitize_text(value: str, repository: Path) -> str:
    roots = ((repository, "."), (Path.home(), "<HOME>"))
    result = value
    for root, replacement in sorted(roots, key=lambda item: len(str(item[0])), reverse=True):
        for spelling in sorted(_path_spellings(root), key=len, reverse=True):
            result = re.sub(
                r"(?<![A-Za-z0-9_.-])" + re.escape(spelling) + r"(?=$|[\\/])",
                replacement,
                result,
            )
    result = _UNC_PATH.sub("<ABSOLUTE_PATH>", result)
    result = _WINDOWS_ABSOLUTE_PATH.sub("<ABSOLUTE_PATH>", result)
    return _POSIX_ABSOLUTE_PATH.sub("<ABSOLUTE_PATH>", result)


def _path_spellings(path: Path) -> set[str]:
    spellings = {str(path), str(path.resolve())}
    for spelling in tuple(spellings):
        if spelling.startswith("/private/"):
            spellings.add(spelling.removeprefix("/private"))
        elif spelling.startswith("/var/"):
            spellings.add("/private" + spelling)
        spellings.add(spelling.replace("/", "\\"))
    return spellings


def _assert_payloads_are_portable(payloads: Mapping[str, bytes]) -> None:
    home = str(Path.home().resolve())
    for path, contents in payloads.items():
        text = contents.decode("utf-8", "replace")
        if home in text or _UNC_PATH.search(text) or _WINDOWS_ABSOLUTE_PATH.search(text) or _POSIX_ABSOLUTE_PATH.search(text):
            raise BundleEvidenceError(
                f"Bundle payload '{path}' still contains an absolute path."
            )


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _pretty_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
