"""Verification evidence creation for Outcome Harness.

This module records mechanical verification and validates saved completion
evidence. It does not invoke a verifier, publish a bundle, or append a ledger
entry.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, TextIO

from .checks import CheckExecutionError, run_checks
from .exit_codes import ExitCode
from .gitdiff import (
    HARNESS_METADATA_DIRECTORIES,
    HARNESS_METADATA_FILES,
    ChangeCollection,
    FileChange,
    GitDiffError,
    GitDiffTaskError,
    collect_changes,
    find_repository_root,
    is_harness_metadata_path,
)
from .run_manifest import RunManifestError, create_run_manifest
from .run_validator import RunIdentityError, RunValidationError, validate_run
from .task import TaskError, show_task, validate_task_id
from .verdict import VerdictEvidenceError, empty_finding_counts, load_recorded_verdict


VERIFICATION_SCHEMA_VERSION = 1
COMPLETION_SCHEMA_VERSION = 1
class EvidenceError(TaskError):
    """Raised when a verification run cannot safely create its evidence."""


class EvidenceRepositoryError(EvidenceError):
    """Raised when Git cannot create or collect verification evidence."""


class CompletionError(EvidenceError):
    """Base error for fail-closed completion evaluation."""

    exit_code = ExitCode.EVIDENCE_MISSING_OR_CORRUPT


class CompletionInputError(CompletionError):
    """Raised when a completion request does not identify its saved Task/run."""

    exit_code = ExitCode.INVALID_INPUT_OR_SCHEMA


class CompletionScopeViolationError(CompletionError):
    """Raised when stored evidence records a product Scope violation."""

    exit_code = ExitCode.SCOPE_VIOLATION


class CompletionRequiredCheckFailureError(CompletionError):
    """Raised when a required recorded check did not pass."""

    exit_code = ExitCode.REQUIRED_CHECK_FAILURE


class CompletionTimeoutError(CompletionError):
    """Raised when a required recorded check timed out."""

    exit_code = ExitCode.TIMEOUT


class CompletionVerifierEvidenceMissingError(CompletionError):
    """Raised when a Task requires a verdict that has not been recorded."""

    exit_code = ExitCode.REQUIRED_VERIFIER_EVIDENCE_MISSING


class CompletionVerifierRejectedError(CompletionError):
    """Raised when a recorded verdict does not satisfy the completion gate."""

    exit_code = ExitCode.REQUIRED_VERIFIER_EVIDENCE_MISSING


class CompletionEvidenceError(CompletionError):
    """Raised when a saved evidence bundle is absent or internally inconsistent."""

    exit_code = ExitCode.EVIDENCE_MISSING_OR_CORRUPT


@dataclass(frozen=True)
class VerificationRun:
    """The identity, location, and final document for one verification run."""

    run_id: str
    evidence_path: Path
    verification: dict[str, Any]


@dataclass(frozen=True)
class CompletionRun:
    """The immutable completion record written for one successful evidence run."""

    task_id: str
    run_id: str
    completion_path: Path
    completion: dict[str, Any]


def verify_task(
    task_id: str,
    *,
    cwd: str | Path | None = None,
    base_ref: str | None = None,
) -> VerificationRun:
    """Run a saved Task's checks and persist its mechanical evidence.

    ``base_ref`` replaces the snapshot baseline for this one run.  Check
    failures are evidence, not CLI errors: all checks run in Task Spec order
    and the resulting mechanical pass/fail is written to ``verification.json``.
    """
    validate_task_id(task_id)
    repository = find_repository_root(cwd)
    task = show_task(task_id, cwd=repository)
    run_id, evidence_path = create_evidence_directory(repository, task_id)
    started = time.monotonic()

    try:
        atomic_write_json(evidence_path / "task.json", task)
        checks = task.get("checks")
        if not isinstance(checks, list):
            raise EvidenceError("Task snapshot checks must be an array.")
        check_results = run_checks(
            checks,
            cwd=repository,
            evidence_directory=evidence_path,
        )

        changes = collect_changes(task, cwd=repository, base_ref=base_ref)
        changed_files = [_file_change_document(change) for change in changes.product_changes]
        scope_violations = [
            _file_change_document(change) for change in changes.out_of_scope_changes
        ]
        atomic_write_json(
            evidence_path / "changed-files.json",
            _changed_files_document(changes),
        )
        atomic_write_bytes(
            evidence_path / "diff.patch",
            collect_diff_patch(repository, changes),
        )
        atomic_write_json(
            evidence_path / "checks.json",
            {"schema_version": VERIFICATION_SCHEMA_VERSION, "checks": check_results},
        )

        required_checks_pass = all(
            bool(result["passed"])
            for result in check_results
            if bool(result["required"])
        )
        scope_pass = changes.scope_passed
        mechanical_result = "pass" if scope_pass and required_checks_pass else "fail"
        evidence_files = _evidence_file_list(check_results)
        verification = {
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "task_id": task_id,
            "run_id": run_id,
            "baseline": changes.base_ref,
            "changed_files": changed_files,
            "scope_pass": scope_pass,
            "scope_violations": scope_violations,
            "required_checks_pass": required_checks_pass,
            "mechanical_result": mechanical_result,
            "evidence_files": evidence_files,
            "timestamp": _utc_timestamp(),
            "duration": max(0.0, time.monotonic() - started),
        }
        atomic_write_json(evidence_path / "verification.json", verification)
        try:
            create_run_manifest(
                evidence_path,
                task_id=task_id,
                run_id=run_id,
                evidence_files=tuple(PurePosixPath(path) for path in evidence_files),
            )
        except RunManifestError as error:
            raise EvidenceError(
                f"Could not create run manifest for Evidence Run '{evidence_path}': {error}"
            ) from error
    except GitDiffTaskError as error:
        raise EvidenceError(str(error)) from error
    except GitDiffError as error:
        raise EvidenceRepositoryError(str(error)) from error
    except CheckExecutionError as error:
        raise EvidenceError(str(error)) from error

    return VerificationRun(
        run_id=run_id,
        evidence_path=evidence_path,
        verification=verification,
    )


def complete_task(
    task_id: str,
    run_id: str,
    *,
    cwd: str | Path | None = None,
) -> CompletionRun:
    """Validate saved mechanical and verifier evidence and write completion.

    Completion never reruns checks, recalculates the Git diff, or chooses a
    latest run.  The caller supplies the exact Task/run pair to evaluate.
    """
    try:
        validated_run = validate_run(task_id, run_id, cwd=cwd)
    except RunIdentityError as error:
        raise CompletionInputError(str(error)) from error
    except RunValidationError as error:
        raise CompletionEvidenceError(str(error)) from error

    task = validated_run.task
    evidence_path = validated_run.evidence_path

    verifier_required = _task_requires_verifier(task)
    try:
        verdict_record = load_recorded_verdict(evidence_path, task_id, run_id)
    except VerdictEvidenceError as error:
        raise CompletionEvidenceError(
            "Saved manual verifier evidence is missing, corrupt, or inconsistent."
        ) from error

    verifier_runner: str | None = None
    verifier_verdict: str | None = None
    try:
        finding_counts = empty_finding_counts()
    except VerdictEvidenceError as error:
        raise CompletionEvidenceError(
            "Could not load Manual Verdict severity definitions."
        ) from error
    if verdict_record is None:
        if verifier_required:
            raise CompletionVerifierEvidenceMissingError(
                "Task requires a valid manual verifier verdict, but no verdict was recorded."
            )
    else:
        verifier = verdict_record.verdict["verifier"]
        verifier_runner = verifier["runner"]
        verifier_verdict = verdict_record.verdict["verdict"]
        finding_counts = verdict_record.counts
        if verifier_verdict != "pass":
            raise CompletionVerifierRejectedError(
                "Completion rejected because the recorded verifier verdict is not pass."
            )
        if finding_counts["blocker"] > 0:
            raise CompletionVerifierRejectedError(
                "Completion rejected because the recorded verifier verdict has blocker findings."
            )
    if not validated_run.scope_pass:
        raise CompletionScopeViolationError(
            "Completion rejected because saved evidence contains a Scope violation."
        )
    if any(record["timed_out"] for record in validated_run.required_check_records):
        raise CompletionTimeoutError(
            "Completion rejected because a required check timed out."
        )
    if not validated_run.required_checks_pass:
        raise CompletionRequiredCheckFailureError(
            "Completion rejected because a required check did not pass."
        )

    completion = {
        "schema_version": COMPLETION_SCHEMA_VERSION,
        "task_id": task_id,
        "run_id": run_id,
        "evidence_sha256": validated_run.evidence_sha256,
        "mechanical_result": "pass",
        "verifier_required": verifier_required,
        "verifier_runner": verifier_runner,
        "verifier_verdict": verifier_verdict,
        "blocker_count": finding_counts["blocker"],
        "warning_count": finding_counts["warning"],
        "note_count": finding_counts["note"],
        "final_result": "pass",
        "completed_at": _utc_timestamp(),
    }
    completion_path = evidence_path / "completion.json"
    atomic_write_json(completion_path, completion)
    return CompletionRun(
        task_id=task_id,
        run_id=run_id,
        completion_path=completion_path,
        completion=completion,
    )


def create_evidence_directory(repository: str | Path, task_id: str) -> tuple[str, Path]:
    """Create and return a collision-free evidence directory for one run."""
    validate_task_id(task_id)
    root = Path(repository).resolve() / ".harness" / "evidence" / task_id
    root.mkdir(parents=True, exist_ok=True)
    for _ in range(100):
        run_id = generate_run_id()
        candidate = root / run_id
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return run_id, candidate
    raise EvidenceError("Could not allocate a unique verification run id.")


def generate_run_id() -> str:
    """Return a path-safe, collision-resistant run id without task metadata."""
    return uuid.uuid4().hex


def atomic_write_json(path: str | Path, value: object) -> None:
    """Write JSON through a same-directory temporary file and rename it atomically."""

    def write(output: TextIO) -> None:
        json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")

    _atomic_write(Path(path), mode="w", writer=write)


def atomic_write_bytes(path: str | Path, value: bytes) -> None:
    """Atomically write a binary artifact using the same no-partial-file rule."""

    def write(output: BinaryIO) -> None:
        output.write(value)

    _atomic_write(Path(path), mode="wb", writer=write)


def _atomic_write(
    path: Path,
    *,
    mode: str,
    writer: Callable[[Any], None],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode=mode,
            encoding="utf-8" if mode == "w" else None,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            writer(output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def collect_diff_patch(repository: str | Path, changes: ChangeCollection) -> bytes:
    """Collect a binary-safe patch for product changes, including untracked files."""
    repository_path = Path(repository).resolve()
    arguments = [
        "git",
        "-C",
        str(repository_path),
        "diff",
        "--binary",
        "--no-ext-diff",
        changes.base_ref,
        "--",
        ".",
        *_metadata_exclude_pathspecs(),
    ]
    patch = _run_git(arguments, accepted_returncodes={0})

    # Git's regular diff intentionally omits untracked paths.  Record each
    # product untracked file with no-index so diff.patch is complete evidence.
    for change in changes.changes:
        if change.source != "untracked" or is_harness_metadata_path(change.path):
            continue
        untracked_patch = _run_git(
            [
                "git",
                "-C",
                str(repository_path),
                "diff",
                "--no-index",
                "--binary",
                "--no-ext-diff",
                "--",
                "/dev/null",
                change.path,
            ],
            accepted_returncodes={0, 1},
        )
        if patch and not patch.endswith(b"\n"):
            patch += b"\n"
        patch += untracked_patch
    return patch


def _run_git(arguments: list[str], *, accepted_returncodes: set[int]) -> bytes:
    try:
        result = subprocess.run(
            arguments,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
    except OSError as error:
        raise EvidenceRepositoryError(
            "Git is required to write verification evidence."
        ) from error
    if result.returncode not in accepted_returncodes:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise EvidenceRepositoryError(
            detail or f"Git diff exited with status {result.returncode}."
        )
    return result.stdout


def _metadata_exclude_pathspecs() -> tuple[str, ...]:
    directories = tuple(f":(exclude){path}/**" for path in HARNESS_METADATA_DIRECTORIES)
    files = tuple(f":(exclude){path}" for path in sorted(HARNESS_METADATA_FILES))
    return directories + files


def _changed_files_document(changes: ChangeCollection) -> dict[str, Any]:
    return {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "baseline": changes.base_ref,
        "scope": list(changes.scope),
        "changes": [_file_change_document(change) for change in changes.changes],
    }


def _file_change_document(change: FileChange) -> dict[str, Any]:
    return {
        "source": change.source,
        "status": change.status,
        "path": change.path,
        "previous_path": change.previous_path,
        "old_mode": change.old_mode,
        "new_mode": change.new_mode,
        "mode_changed": change.mode_changed,
        "is_binary": change.is_binary,
        "in_scope": change.in_scope,
    }


def _evidence_file_list(check_results: list[dict[str, Any]]) -> list[str]:
    files = ["task.json", "changed-files.json", "diff.patch", "checks.json"]
    for result in check_results:
        files.extend((str(result["stdout_path"]), str(result["stderr_path"])))
    files.append("verification.json")
    return files


def _task_requires_verifier(task: Mapping[str, Any]) -> bool:
    verifier = task.get("verifier")
    if not isinstance(verifier, Mapping) or type(verifier.get("required")) is not bool:
        raise CompletionInputError("Saved Task snapshot verifier must contain required boolean.")
    return bool(verifier["required"])


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
