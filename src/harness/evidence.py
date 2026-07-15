"""Verification evidence creation for Outcome Harness.

This module records mechanical verification only.  It deliberately does not
decide Task completion, invoke a verifier, publish a bundle, or append a
ledger entry.
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
from .task import TaskError, show_task, validate_task_id


VERIFICATION_SCHEMA_VERSION = 1
COMPLETION_SCHEMA_VERSION = 1
RUN_ID_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)
_REQUIRED_EVIDENCE_FILES = (
    "task.json",
    "changed-files.json",
    "diff.patch",
    "checks.json",
    "verification.json",
)


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
    """Raised when the Task requires verifier evidence unavailable in Phase 1c."""

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
    """Validate saved mechanical evidence and write its completion record.

    Completion never reruns checks, recalculates the Git diff, or chooses a
    latest run.  The caller supplies the exact Task/run pair to evaluate.
    Phase 1c intentionally has no independent verifier evidence format, so a
    Task that requires one cannot complete here.
    """
    validate_task_id(task_id)
    validate_run_id(run_id)
    repository = find_repository_root(cwd)
    task = show_task(task_id, cwd=repository)
    evidence_path = repository / ".harness" / "evidence" / task_id / run_id

    evidence_task = _read_evidence_json(evidence_path, "task.json")
    changed_files = _read_evidence_json(evidence_path, "changed-files.json")
    checks_document = _read_evidence_json(evidence_path, "checks.json")
    verification = _read_evidence_json(evidence_path, "verification.json")
    _require_evidence_file(evidence_path / "diff.patch")
    _require_schema_version(evidence_task, "task.json")
    _require_schema_version(changed_files, "changed-files.json")
    _require_schema_version(checks_document, "checks.json")
    _require_schema_version(verification, "verification.json")
    _require_listed_evidence_files(evidence_path, verification)

    if evidence_task != task:
        raise CompletionInputError(
            f"Evidence task snapshot does not match saved Task '{task_id}'."
        )

    recorded_task_id = _require_string(verification, "task_id", "verification.json")
    recorded_run_id = _require_string(verification, "run_id", "verification.json")
    if recorded_task_id != task_id or recorded_run_id != run_id:
        raise CompletionInputError(
            "Evidence task/run identity does not match the requested Task and run id."
        )

    scope_pass = _require_boolean(verification, "scope_pass", "verification.json")
    required_checks_pass = _require_boolean(
        verification, "required_checks_pass", "verification.json"
    )
    mechanical_result = _require_string(
        verification, "mechanical_result", "verification.json"
    )
    if mechanical_result not in {"pass", "fail"}:
        raise CompletionEvidenceError(
            "verification.json mechanical_result must be 'pass' or 'fail'."
        )

    required_records = _validate_check_evidence(task, checks_document)
    computed_required_checks_pass = all(
        bool(record["passed"]) for record in required_records
    )
    expected_mechanical_result = (
        "pass" if scope_pass and computed_required_checks_pass else "fail"
    )
    if required_checks_pass != computed_required_checks_pass:
        raise CompletionEvidenceError(
            "verification.json required_checks_pass does not match checks.json."
        )
    if mechanical_result != expected_mechanical_result:
        raise CompletionEvidenceError(
            "verification.json mechanical_result does not match its saved evidence."
        )

    if _task_requires_verifier(task):
        raise CompletionVerifierEvidenceMissingError(
            "Task requires independent verifier evidence, which Phase 1c does not record."
        )
    if not scope_pass:
        raise CompletionScopeViolationError(
            "Completion rejected because saved evidence contains a Scope violation."
        )
    if any(bool(record["timed_out"]) for record in required_records):
        raise CompletionTimeoutError(
            "Completion rejected because a required check timed out."
        )
    if not computed_required_checks_pass:
        raise CompletionRequiredCheckFailureError(
            "Completion rejected because a required check did not pass."
        )

    completion = {
        "schema_version": COMPLETION_SCHEMA_VERSION,
        "task_id": task_id,
        "run_id": run_id,
        "mechanical_result": "pass",
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


def validate_run_id(run_id: object) -> str:
    """Validate a caller-supplied run id before using it in an evidence path."""
    if not isinstance(run_id, str) or not run_id:
        raise CompletionInputError("Run id must be a non-empty string.")
    if run_id[0] not in RUN_ID_CHARACTERS - {"_", "-"}:
        raise CompletionInputError(
            "Run id must begin with an alphanumeric character and contain only "
            "letters, numbers, underscores, or hyphens."
        )
    if any(character not in RUN_ID_CHARACTERS for character in run_id):
        raise CompletionInputError(
            "Run id must contain only letters, numbers, underscores, or hyphens."
        )
    return run_id


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


def _read_evidence_json(evidence_path: Path, filename: str) -> dict[str, Any]:
    path = evidence_path / filename
    _require_evidence_file(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CompletionEvidenceError(f"Evidence file '{filename}' is not valid JSON.") from error
    if not isinstance(document, Mapping):
        raise CompletionEvidenceError(f"Evidence file '{filename}' must be a JSON object.")
    return dict(document)


def _require_evidence_file(path: Path) -> None:
    if not path.is_file():
        raise CompletionEvidenceError(f"Required evidence file is missing: {path.name}.")


def _require_schema_version(document: Mapping[str, Any], filename: str) -> None:
    if document.get("schema_version") != VERIFICATION_SCHEMA_VERSION:
        raise CompletionEvidenceError(
            f"Evidence file '{filename}' has an unsupported schema_version."
        )


def _require_listed_evidence_files(
    evidence_path: Path, verification: Mapping[str, Any]
) -> None:
    raw_files = verification.get("evidence_files")
    if not isinstance(raw_files, list) or not raw_files:
        raise CompletionEvidenceError(
            "verification.json evidence_files must be a non-empty array."
        )
    listed_files: set[str] = set()
    for index, value in enumerate(raw_files):
        if not isinstance(value, str) or not value:
            raise CompletionEvidenceError(
                f"verification.json evidence_files[{index}] must be a non-empty string."
            )
        relative_path = _safe_evidence_relative_path(value)
        normalized = relative_path.as_posix()
        if normalized in listed_files:
            raise CompletionEvidenceError(
                f"verification.json lists evidence file '{normalized}' more than once."
            )
        listed_files.add(normalized)
        _require_evidence_file(evidence_path.joinpath(*relative_path.parts))

    missing = set(_REQUIRED_EVIDENCE_FILES) - listed_files
    if missing:
        names = ", ".join(sorted(missing))
        raise CompletionEvidenceError(
            f"verification.json evidence_files is missing required entry(s): {names}."
        )


def _safe_evidence_relative_path(value: str) -> PurePosixPath:
    if "\\" in value:
        raise CompletionEvidenceError("Evidence file paths must use relative POSIX paths.")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise CompletionEvidenceError("Evidence file paths must stay inside the run directory.")
    return path


def _require_string(document: Mapping[str, Any], field: str, filename: str) -> str:
    value = document.get(field)
    if not isinstance(value, str) or not value:
        raise CompletionEvidenceError(
            f"Evidence file '{filename}' field '{field}' must be a non-empty string."
        )
    return value


def _require_boolean(document: Mapping[str, Any], field: str, filename: str) -> bool:
    value = document.get(field)
    if type(value) is not bool:
        raise CompletionEvidenceError(
            f"Evidence file '{filename}' field '{field}' must be a boolean."
        )
    return value


def _validate_check_evidence(
    task: Mapping[str, Any], checks_document: Mapping[str, Any]
) -> list[dict[str, Any]]:
    task_checks = task.get("checks")
    if not isinstance(task_checks, list):
        raise CompletionInputError("Saved Task snapshot checks must be an array.")
    recorded_checks = checks_document.get("checks")
    if not isinstance(recorded_checks, list):
        raise CompletionEvidenceError("checks.json checks must be an array.")
    if len(recorded_checks) != len(task_checks):
        raise CompletionEvidenceError(
            "checks.json does not contain one result for every Task check."
        )

    required_records: list[dict[str, Any]] = []
    for index, (task_check, recorded_check) in enumerate(zip(task_checks, recorded_checks)):
        if not isinstance(task_check, Mapping):
            raise CompletionInputError(f"Saved Task check at index {index} is invalid.")
        expected_name = task_check.get("name")
        expected_argv = task_check.get("argv")
        expected_required = task_check.get("required")
        if (
            not isinstance(expected_name, str)
            or not isinstance(expected_argv, list)
            or type(expected_required) is not bool
        ):
            raise CompletionInputError(f"Saved Task check at index {index} is invalid.")
        if not isinstance(recorded_check, Mapping):
            raise CompletionEvidenceError(f"checks.json check at index {index} is invalid.")
        record = dict(recorded_check)
        if (
            record.get("name") != expected_name
            or record.get("argv") != expected_argv
            or record.get("required") is not expected_required
        ):
            raise CompletionEvidenceError(
                f"checks.json check at index {index} does not match the saved Task."
            )
        if type(record.get("passed")) is not bool or type(record.get("timed_out")) is not bool:
            raise CompletionEvidenceError(
                f"checks.json check at index {index} is missing pass/timeout state."
            )
        if record["timed_out"] and record["passed"]:
            raise CompletionEvidenceError(
                f"checks.json check at index {index} cannot both time out and pass."
            )
        if expected_required:
            required_records.append(record)
    return required_records


def _task_requires_verifier(task: Mapping[str, Any]) -> bool:
    verifier = task.get("verifier")
    if not isinstance(verifier, Mapping) or type(verifier.get("required")) is not bool:
        raise CompletionInputError("Saved Task snapshot verifier must contain required boolean.")
    return bool(verifier["required"])


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
