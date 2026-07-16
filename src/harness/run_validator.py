"""Canonical validation for stored Outcome Harness evidence Runs.

``validate_run`` reads only one saved Task/run pair.  It never reruns checks,
collects a new Git diff, compares the current source tree, or evaluates
completion policy.  A Run with failed checks, a timeout, or a Scope violation
can therefore still be structurally valid and return ``ValidatedRun``.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .checks import DEFAULT_CHECK_TIMEOUT_SECONDS
from .run_manifest import RunManifestError, load_and_validate_run_manifest
from .task import TASK_SCHEMA_VERSION, TaskError, TaskRepositoryError, validate_task_id


RUN_EVIDENCE_SCHEMA_VERSION = 1
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
_VERIFICATION_FIELDS = frozenset(
    {
        "schema_version",
        "task_id",
        "run_id",
        "baseline",
        "changed_files",
        "scope_pass",
        "scope_violations",
        "required_checks_pass",
        "mechanical_result",
        "evidence_files",
        "timestamp",
        "duration",
    }
)
_CHANGED_FILES_FIELDS = frozenset({"schema_version", "baseline", "scope", "changes"})
_CHECKS_FIELDS = frozenset({"schema_version", "checks"})
_CHECK_RECORD_FIELDS = frozenset(
    {
        "name",
        "argv",
        "cwd",
        "started_at",
        "finished_at",
        "duration_seconds",
        "effective_timeout",
        "exit_code",
        "timed_out",
        "stdout_path",
        "stderr_path",
        "required",
        "passed",
    }
)
_FILE_CHANGE_FIELDS = frozenset(
    {
        "source",
        "status",
        "path",
        "previous_path",
        "old_mode",
        "new_mode",
        "mode_changed",
        "is_binary",
        "in_scope",
    }
)
_CHANGE_SOURCES = frozenset({"committed", "staged", "unstaged", "untracked"})
_HARNESS_METADATA_DIRECTORIES = (".harness/tasks", ".harness/evidence")
_HARNESS_METADATA_FILES = frozenset(
    {".harness/runs.jsonl", ".harness/lessons.md", ".harness/config.json"}
)


class RunValidationError(TaskError):
    """Raised when saved Task/run evidence cannot be read consistently."""


class RunIdentityError(RunValidationError):
    """Raised when requested or recorded Task/run identity is inconsistent."""


class RunEvidenceError(RunValidationError):
    """Raised when a stored evidence artifact is missing, unsafe, or corrupt."""


class _FrozenDict(dict[str, Any]):
    """A JSON-compatible dict that rejects mutation after construction."""

    def _immutable(self, *args: object, **kwargs: object) -> None:
        raise TypeError("Validated Run data is immutable.")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


class _FrozenList(list[Any]):
    """A JSON-compatible list that rejects mutation after construction."""

    def _immutable(self, *args: object, **kwargs: object) -> None:
        raise TypeError("Validated Run data is immutable.")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable


@dataclass(frozen=True)
class ValidatedRun:
    """An independent, internally consistent snapshot of one saved Run.

    The dataclass is frozen and every JSON-derived value is copied before it is
    returned, so callers cannot mutate the objects used during validation or
    the evidence files on disk through an alias.
    """

    repository: Path
    task_id: str
    run_id: str
    evidence_path: Path

    task: dict[str, Any]
    changed_files: dict[str, Any]
    checks: dict[str, Any]
    verification: dict[str, Any]
    diff_patch: bytes

    check_records: tuple[dict[str, Any], ...]
    required_check_records: tuple[dict[str, Any], ...]
    log_paths: tuple[PurePosixPath, ...]
    evidence_sha256: str

    scope_pass: bool
    required_checks_pass: bool
    mechanical_result: str


def validate_run(
    task_id: str,
    run_id: str,
    *,
    cwd: str | Path | None = None,
) -> ValidatedRun:
    """Validate and return one stored Task/run without executing any checks.

    This is the single integrity boundary for persisted mechanical Evidence.
    It validates the saved files against each other, but deliberately does not
    bind them to a later working-tree state or inspect current product files.
    """
    _validate_requested_identity(task_id, run_id)
    repository = _find_repository_root(cwd)
    task = _read_saved_task_snapshot(repository, task_id)
    _validate_task_snapshot(task, task_id, "saved Task snapshot")

    evidence_path = _validated_evidence_directory(repository, task_id, run_id)
    evidence_task = _read_evidence_json(evidence_path, PurePosixPath("task.json"))
    changed_files = _read_evidence_json(evidence_path, PurePosixPath("changed-files.json"))
    checks = _read_evidence_json(evidence_path, PurePosixPath("checks.json"))
    verification = _read_evidence_json(evidence_path, PurePosixPath("verification.json"))
    diff_patch = _read_evidence_bytes(evidence_path, PurePosixPath("diff.patch"))

    _validate_task_snapshot(evidence_task, task_id, "task.json")
    if evidence_task != task:
        raise RunIdentityError(
            f"task.json does not match saved Task snapshot '{task_id}'."
        )

    _validate_verification_document(verification)
    if verification["task_id"] != task_id:
        raise RunIdentityError(
            "verification.json task_id does not match the requested Task id."
        )
    if verification["run_id"] != run_id:
        raise RunIdentityError(
            "verification.json run_id does not match the requested run id."
        )

    evidence_files = _validate_listed_evidence_files(evidence_path, verification)
    check_records, required_records, log_paths = _validate_check_records(
        task,
        checks,
        evidence_files,
        evidence_path,
    )
    computed_scope_pass = _validate_changed_files(
        task,
        changed_files,
        verification,
    )
    computed_required_checks_pass = all(record["passed"] for record in required_records)
    computed_mechanical_result = (
        "pass" if computed_scope_pass and computed_required_checks_pass else "fail"
    )
    if verification["required_checks_pass"] != computed_required_checks_pass:
        raise RunEvidenceError(
            "verification.json required_checks_pass does not match checks.json."
        )
    if verification["mechanical_result"] != computed_mechanical_result:
        raise RunEvidenceError(
            "verification.json mechanical_result does not match saved scope and checks."
        )

    expected_evidence_files = _expected_mechanical_evidence_files(log_paths)
    _validate_exact_evidence_file_list(evidence_files, expected_evidence_files)
    try:
        manifest = load_and_validate_run_manifest(
            evidence_path,
            expected_task_id=task_id,
            expected_run_id=run_id,
            expected_files=expected_evidence_files,
        )
    except RunManifestError as error:
        raise RunEvidenceError(str(error)) from error

    return ValidatedRun(
        repository=repository,
        task_id=task_id,
        run_id=run_id,
        evidence_path=evidence_path,
        task=_freeze_json(task),
        changed_files=_freeze_json(changed_files),
        checks=_freeze_json(checks),
        verification=_freeze_json(verification),
        diff_patch=bytes(diff_patch),
        check_records=tuple(_freeze_json(record) for record in check_records),
        required_check_records=tuple(_freeze_json(record) for record in required_records),
        log_paths=tuple(log_paths),
        evidence_sha256=manifest.evidence_sha256,
        scope_pass=computed_scope_pass,
        required_checks_pass=computed_required_checks_pass,
        mechanical_result=computed_mechanical_result,
    )


def _freeze_json(value: Any) -> Any:
    """Create a deep, JSON-compatible immutable snapshot without aliases."""
    if isinstance(value, Mapping):
        frozen = _FrozenDict()
        for key, item in value.items():
            dict.__setitem__(frozen, copy.deepcopy(key), _freeze_json(item))
        return frozen
    if isinstance(value, list):
        frozen_list = _FrozenList()
        for item in value:
            list.append(frozen_list, _freeze_json(item))
        return frozen_list
    return copy.deepcopy(value)


def validate_run_id(run_id: object) -> str:
    """Validate a path-safe Run id for stored evidence lookup."""
    if not isinstance(run_id, str) or not run_id:
        raise RunIdentityError("Run id must be a non-empty string.")
    if run_id[0] not in RUN_ID_CHARACTERS - {"_", "-"}:
        raise RunIdentityError(
            "Run id must begin with an alphanumeric character and contain only "
            "letters, numbers, underscores, or hyphens."
        )
    if any(character not in RUN_ID_CHARACTERS for character in run_id):
        raise RunIdentityError(
            "Run id must contain only letters, numbers, underscores, or hyphens."
        )
    return run_id


def _validate_requested_identity(task_id: object, run_id: object) -> None:
    try:
        validate_task_id(task_id)
    except TaskError as error:
        raise RunIdentityError(str(error)) from error
    validate_run_id(run_id)


def _find_repository_root(cwd: str | Path | None) -> Path:
    """Locate the enclosing worktree without invoking Git or another CLI."""
    working_directory = Path.cwd() if cwd is None else Path(cwd)
    try:
        resolved = working_directory.resolve()
    except OSError as error:
        raise TaskRepositoryError("Task commands must run inside a Git repository.") from error
    start = resolved if resolved.is_dir() else resolved.parent
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise TaskRepositoryError("Task commands must run inside a Git repository.")


def _read_saved_task_snapshot(repository: Path, task_id: str) -> dict[str, Any]:
    path = repository / ".harness" / "tasks" / f"{task_id}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RunIdentityError(f"Saved Task snapshot '{task_id}' does not exist.") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RunIdentityError(
            f"Saved Task snapshot '{task_id}' is unreadable or invalid JSON."
        ) from error
    if not isinstance(value, Mapping):
        raise RunIdentityError(f"Saved Task snapshot '{task_id}' must be a JSON object.")
    return dict(value)


def _validated_evidence_directory(repository: Path, task_id: str, run_id: str) -> Path:
    logical_path = repository / ".harness" / "evidence" / task_id / run_id
    try:
        evidence_directories = (
            repository / ".harness",
            repository / ".harness" / "evidence",
            repository / ".harness" / "evidence" / task_id,
            logical_path,
        )
        if any(path.is_symlink() for path in evidence_directories) or not logical_path.is_dir():
            raise RunEvidenceError(
                f"Evidence Run directory is missing or unsafe: {task_id}/{run_id}."
            )
        evidence_path = logical_path.resolve(strict=True)
    except OSError as error:
        raise RunEvidenceError(
            f"Evidence Run directory is missing or unreadable: {task_id}/{run_id}."
        ) from error

    if not evidence_path.is_relative_to(repository.resolve()):
        raise RunEvidenceError(
            "Evidence Run directory must remain inside the repository."
        )
    return evidence_path


def _read_evidence_json(evidence_path: Path, relative_path: PurePosixPath) -> dict[str, Any]:
    try:
        value = json.loads(_read_evidence_bytes(evidence_path, relative_path).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RunEvidenceError(
            f"Evidence file '{relative_path.as_posix()}' is not valid JSON."
        ) from error
    if not isinstance(value, Mapping):
        raise RunEvidenceError(
            f"Evidence file '{relative_path.as_posix()}' must be a JSON object."
        )
    return dict(value)


def _read_evidence_bytes(evidence_path: Path, relative_path: PurePosixPath) -> bytes:
    candidate = evidence_path.joinpath(*relative_path.parts)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise RunEvidenceError(
            f"Required evidence file is missing: {relative_path.as_posix()}."
        ) from error
    if not resolved.is_relative_to(evidence_path) or not resolved.is_file():
        raise RunEvidenceError(
            f"Required evidence file is unsafe or missing: {relative_path.as_posix()}."
        )
    try:
        return resolved.read_bytes()
    except OSError as error:
        raise RunEvidenceError(
            f"Could not read evidence file: {relative_path.as_posix()}."
        ) from error


def _validate_task_snapshot(task: Mapping[str, Any], task_id: str, context: str) -> None:
    if type(task.get("schema_version")) is not int or task["schema_version"] != TASK_SCHEMA_VERSION:
        raise RunIdentityError(f"{context} has an unsupported schema_version.")
    if task.get("id") != task_id:
        raise RunIdentityError(f"{context} id does not match requested Task id '{task_id}'.")
    if not isinstance(task.get("baseline"), str) or not task["baseline"]:
        raise RunIdentityError(f"{context} baseline must be a non-empty string.")
    _task_scope(task, context)
    _task_checks(task, context)
    verifier = task.get("verifier")
    if not isinstance(verifier, Mapping) or type(verifier.get("required")) is not bool:
        raise RunIdentityError(f"{context} verifier must contain a required boolean.")


def _task_scope(task: Mapping[str, Any], context: str) -> tuple[str, ...]:
    raw_scope = task.get("scope")
    if not isinstance(raw_scope, list) or not raw_scope:
        raise RunIdentityError(f"{context} scope must be a non-empty array.")
    return tuple(
        _safe_repository_relative_path(value, f"{context} scope[{index}]", allow_dot=True)
        for index, value in enumerate(raw_scope)
    )


def _task_checks(task: Mapping[str, Any], context: str) -> tuple[dict[str, Any], ...]:
    raw_checks = task.get("checks")
    if not isinstance(raw_checks, list) or not raw_checks:
        raise RunIdentityError(f"{context} checks must be a non-empty array.")

    checks: list[dict[str, Any]] = []
    for index, value in enumerate(raw_checks):
        if not isinstance(value, Mapping):
            raise RunIdentityError(f"{context} checks[{index}] must be an object.")
        name = value.get("name")
        argv = value.get("argv")
        required = value.get("required")
        if not isinstance(name, str) or not name:
            raise RunIdentityError(f"{context} checks[{index}].name must be a non-empty string.")
        if not isinstance(argv, list) or not argv or not all(
            isinstance(argument, str) and argument for argument in argv
        ):
            raise RunIdentityError(f"{context} checks[{index}].argv must be a non-empty string array.")
        if type(required) is not bool:
            raise RunIdentityError(f"{context} checks[{index}].required must be a boolean.")
        timeout = value.get("timeout_seconds", DEFAULT_CHECK_TIMEOUT_SECONDS)
        if type(timeout) is not int or timeout <= 0:
            raise RunIdentityError(
                f"{context} checks[{index}].timeout_seconds must be a positive integer."
            )
        checks.append(dict(value))
    return tuple(checks)


def _validate_verification_document(verification: Mapping[str, Any]) -> None:
    _require_exact_keys(verification, _VERIFICATION_FIELDS, "verification.json")
    _require_schema_version(verification, "verification.json")
    _require_nonempty_string(verification.get("task_id"), "verification.json task_id")
    _require_nonempty_string(verification.get("run_id"), "verification.json run_id")
    _require_nonempty_string(verification.get("baseline"), "verification.json baseline")
    _require_list(verification.get("changed_files"), "verification.json changed_files")
    _require_boolean(verification.get("scope_pass"), "verification.json scope_pass")
    _require_list(verification.get("scope_violations"), "verification.json scope_violations")
    _require_boolean(
        verification.get("required_checks_pass"), "verification.json required_checks_pass"
    )
    if verification.get("mechanical_result") not in {"pass", "fail"}:
        raise RunEvidenceError("verification.json mechanical_result must be 'pass' or 'fail'.")
    _require_list(verification.get("evidence_files"), "verification.json evidence_files")
    _require_nonempty_string(verification.get("timestamp"), "verification.json timestamp")
    duration = verification.get("duration")
    if type(duration) not in {int, float} or duration < 0:
        raise RunEvidenceError("verification.json duration must be a non-negative number.")


def _validate_listed_evidence_files(
    evidence_path: Path, verification: Mapping[str, Any]
) -> dict[str, PurePosixPath]:
    raw_files = verification["evidence_files"]
    assert isinstance(raw_files, list)  # Checked by _validate_verification_document.
    if not raw_files:
        raise RunEvidenceError("verification.json evidence_files must be a non-empty array.")

    listed_files: dict[str, PurePosixPath] = {}
    for index, value in enumerate(raw_files):
        relative_path = _safe_evidence_relative_path(
            value, f"verification.json evidence_files[{index}]"
        )
        normalized = relative_path.as_posix()
        if normalized in listed_files:
            raise RunEvidenceError(
                f"verification.json evidence_files[{index}] duplicates '{normalized}'."
            )
        listed_files[normalized] = relative_path
        _read_evidence_bytes(evidence_path, relative_path)

    missing = set(_REQUIRED_EVIDENCE_FILES) - set(listed_files)
    if missing:
        names = ", ".join(sorted(missing))
        raise RunEvidenceError(
            f"verification.json evidence_files is missing required entry(s): {names}."
        )
    return listed_files


def _expected_mechanical_evidence_files(
    log_paths: tuple[PurePosixPath, ...],
) -> tuple[PurePosixPath, ...]:
    return tuple(
        PurePosixPath(path)
        for path in sorted(
            (*_REQUIRED_EVIDENCE_FILES, *(path.as_posix() for path in log_paths))
        )
    )


def _validate_exact_evidence_file_list(
    evidence_files: Mapping[str, PurePosixPath],
    expected_files: tuple[PurePosixPath, ...],
) -> None:
    expected = {path.as_posix() for path in expected_files}
    listed = set(evidence_files)
    if listed == expected:
        return
    missing = sorted(expected - listed)
    if missing:
        raise RunEvidenceError(
            "verification.json evidence_files is missing expected mechanical entry(s): "
            + ", ".join(missing)
            + "."
        )
    unexpected = sorted(listed - expected)
    raise RunEvidenceError(
        "verification.json evidence_files has unexpected non-mechanical entry(s): "
        + ", ".join(unexpected)
        + "."
    )


def _validate_check_records(
    task: Mapping[str, Any],
    checks_document: Mapping[str, Any],
    evidence_files: Mapping[str, PurePosixPath],
    evidence_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], tuple[PurePosixPath, ...]]:
    _require_exact_keys(checks_document, _CHECKS_FIELDS, "checks.json")
    _require_schema_version(checks_document, "checks.json")
    recorded_checks = checks_document.get("checks")
    if not isinstance(recorded_checks, list):
        raise RunEvidenceError("checks.json checks must be an array.")

    task_checks = _task_checks(task, "saved Task snapshot")
    if len(recorded_checks) != len(task_checks):
        raise RunEvidenceError("checks.json does not contain one result for every Task check.")

    records: list[dict[str, Any]] = []
    required_records: list[dict[str, Any]] = []
    log_paths: list[PurePosixPath] = []
    seen_log_paths = set(_REQUIRED_EVIDENCE_FILES)
    for index, (task_check, recorded_check) in enumerate(zip(task_checks, recorded_checks)):
        context = f"checks.json checks[{index}]"
        if not isinstance(recorded_check, Mapping):
            raise RunEvidenceError(f"{context} must be an object.")
        _require_exact_keys(recorded_check, _CHECK_RECORD_FIELDS, context)
        record = dict(recorded_check)
        for field in ("name", "argv", "required"):
            if record[field] != task_check[field]:
                raise RunEvidenceError(
                    f"{context}.{field} does not match saved Task check[{index}].{field}."
                )

        _require_nonempty_string(record.get("cwd"), f"{context}.cwd")
        _require_nonempty_string(record.get("started_at"), f"{context}.started_at")
        _require_nonempty_string(record.get("finished_at"), f"{context}.finished_at")
        duration = record.get("duration_seconds")
        if type(duration) not in {int, float} or duration < 0:
            raise RunEvidenceError(f"{context}.duration_seconds must be a non-negative number.")
        expected_timeout = task_check.get("timeout_seconds", DEFAULT_CHECK_TIMEOUT_SECONDS)
        if record.get("effective_timeout") != expected_timeout:
            raise RunEvidenceError(
                f"{context}.effective_timeout does not match saved Task check[{index}]."
            )

        passed = record.get("passed")
        timed_out = record.get("timed_out")
        exit_code = record.get("exit_code")
        if type(passed) is not bool:
            raise RunEvidenceError(f"{context}.passed must be a boolean.")
        if type(timed_out) is not bool:
            raise RunEvidenceError(f"{context}.timed_out must be a boolean.")
        if exit_code is not None and type(exit_code) is not int:
            raise RunEvidenceError(f"{context}.exit_code must be an integer or null.")
        if passed != (not timed_out and exit_code == 0):
            raise RunEvidenceError(
                f"{context}.passed does not match timed_out and exit_code."
            )

        for field in ("stdout_path", "stderr_path"):
            relative_path = _safe_evidence_relative_path(record.get(field), f"{context}.{field}")
            normalized = relative_path.as_posix()
            if normalized not in evidence_files:
                raise RunEvidenceError(
                    f"{context}.{field} is not listed in verification.json evidence_files."
                )
            if normalized in seen_log_paths:
                raise RunEvidenceError(
                    f"{context}.{field} duplicates an existing evidence path '{normalized}'."
                )
            seen_log_paths.add(normalized)
            _read_evidence_bytes(evidence_path, relative_path)
            log_paths.append(relative_path)

        records.append(record)
        if bool(record["required"]):
            required_records.append(record)
    return records, required_records, tuple(log_paths)


def _validate_changed_files(
    task: Mapping[str, Any],
    changed_files: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> bool:
    _require_exact_keys(changed_files, _CHANGED_FILES_FIELDS, "changed-files.json")
    _require_schema_version(changed_files, "changed-files.json")
    baseline = _require_nonempty_string(changed_files.get("baseline"), "changed-files.json baseline")
    if baseline != verification["baseline"]:
        raise RunEvidenceError("changed-files.json baseline does not match verification.json baseline.")

    task_scope = _task_scope(task, "saved Task snapshot")
    raw_scope = changed_files.get("scope")
    if not isinstance(raw_scope, list):
        raise RunEvidenceError("changed-files.json scope must be an array.")
    recorded_scope = tuple(
        _safe_repository_relative_path(value, f"changed-files.json scope[{index}]", allow_dot=True)
        for index, value in enumerate(raw_scope)
    )
    if recorded_scope != task_scope:
        raise RunEvidenceError("changed-files.json scope does not match saved Task scope.")

    raw_changes = changed_files.get("changes")
    if not isinstance(raw_changes, list):
        raise RunEvidenceError("changed-files.json changes must be an array.")
    changes = [
        _validate_file_change(value, f"changed-files.json changes[{index}]", task_scope)
        for index, value in enumerate(raw_changes)
    ]
    product_changes = [change for change in changes if not _is_harness_metadata_change(change)]
    expected_violations = [change for change in product_changes if not change["in_scope"]]

    recorded_product_changes = verification["changed_files"]
    assert isinstance(recorded_product_changes, list)
    if recorded_product_changes != product_changes:
        raise RunEvidenceError(
            "verification.json changed_files does not match product changes in changed-files.json."
        )
    recorded_violations = verification["scope_violations"]
    assert isinstance(recorded_violations, list)
    if recorded_violations != expected_violations:
        raise RunEvidenceError(
            "verification.json scope_violations does not match out-of-scope product changes."
        )

    computed_scope_pass = not expected_violations
    if verification["scope_pass"] != computed_scope_pass:
        raise RunEvidenceError(
            "verification.json scope_pass does not match scope_violations."
        )
    return computed_scope_pass


def _validate_file_change(
    value: object, context: str, scope: tuple[str, ...]
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RunEvidenceError(f"{context} must be an object.")
    _require_exact_keys(value, _FILE_CHANGE_FIELDS, context)
    source = value.get("source")
    if source not in _CHANGE_SOURCES:
        raise RunEvidenceError(f"{context}.source is invalid.")
    _require_nonempty_string(value.get("status"), f"{context}.status")
    path = _safe_repository_relative_path(value.get("path"), f"{context}.path")
    previous_value = value.get("previous_path")
    previous_path = (
        None
        if previous_value is None
        else _safe_repository_relative_path(previous_value, f"{context}.previous_path")
    )
    for field in ("old_mode", "new_mode"):
        mode = value.get(field)
        if mode is not None and (not isinstance(mode, str) or not mode):
            raise RunEvidenceError(f"{context}.{field} must be a non-empty string or null.")
    for field in ("mode_changed", "is_binary", "in_scope"):
        _require_boolean(value.get(field), f"{context}.{field}")

    paths = (path,) if previous_path is None else (path, previous_path)
    expected_in_scope = any(_path_is_within(path_value, boundary) for path_value in paths for boundary in scope)
    if value["in_scope"] != expected_in_scope:
        raise RunEvidenceError(f"{context}.in_scope does not match saved Task scope.")
    return dict(value)


def _is_harness_metadata_change(change: Mapping[str, Any]) -> bool:
    paths = [change["path"]]
    previous_path = change["previous_path"]
    if previous_path is not None:
        paths.append(previous_path)
    return all(_is_harness_metadata_path(path) for path in paths)


def _is_harness_metadata_path(path: str) -> bool:
    if path in _HARNESS_METADATA_FILES:
        return True
    return any(_path_is_within(path, directory) for directory in _HARNESS_METADATA_DIRECTORIES)


def _path_is_within(path: str, boundary: str) -> bool:
    if boundary == ".":
        return True
    path_parts = path.split("/")
    boundary_parts = boundary.split("/")
    return len(path_parts) >= len(boundary_parts) and path_parts[: len(boundary_parts)] == boundary_parts


def _safe_evidence_relative_path(value: object, context: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise RunEvidenceError(f"{context} must be a non-empty relative POSIX path.")
    if "\\" in value or "\x00" in value:
        raise RunEvidenceError(f"{context} must use a relative POSIX path.")
    path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    parts = value.split("/")
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or not path.parts
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise RunEvidenceError(f"{context} must stay inside the Run directory.")
    return path


def _safe_repository_relative_path(
    value: object, context: str, *, allow_dot: bool = False
) -> str:
    if not isinstance(value, str) or not value:
        raise RunEvidenceError(f"{context} must be a non-empty repository-relative path.")
    if allow_dot and value == ".":
        return value
    if "\\" in value or "\x00" in value:
        raise RunEvidenceError(f"{context} must use a repository-relative POSIX path.")
    path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    parts = value.split("/")
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or not path.parts
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise RunEvidenceError(f"{context} must be a repository-relative path.")
    return path.as_posix()


def _require_exact_keys(value: Mapping[str, Any], expected: frozenset[str], context: str) -> None:
    missing = expected - set(value)
    unexpected = set(value) - expected
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unexpected:
            details.append("unexpected " + ", ".join(sorted(unexpected)))
        raise RunEvidenceError(f"{context} has " + "; ".join(details) + " field(s).")


def _require_schema_version(document: Mapping[str, Any], filename: str) -> None:
    if (
        type(document.get("schema_version")) is not int
        or document["schema_version"] != RUN_EVIDENCE_SCHEMA_VERSION
    ):
        raise RunEvidenceError(f"{filename} has an unsupported schema_version.")


def _require_nonempty_string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise RunEvidenceError(f"{context} must be a non-empty string.")
    return value


def _require_boolean(value: object, context: str) -> bool:
    if type(value) is not bool:
        raise RunEvidenceError(f"{context} must be a boolean.")
    return value


def _require_list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise RunEvidenceError(f"{context} must be an array.")
    return value
