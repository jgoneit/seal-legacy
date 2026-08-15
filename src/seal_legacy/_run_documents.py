"""Internal validation of persisted mechanical Evidence documents."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from ._path_policy import (
    change_is_within_scope as _change_is_within_scope,
    is_seal_metadata_path as _is_seal_metadata_path,
)
from ._run_artifact_io import (
    RunArtifactPathError,
    RunArtifactReadError,
    read_run_artifact_bytes,
    safe_run_relative_path,
)
from ._source_binding_documents import (
    SOURCE_BINDING_EVIDENCE_FILES,
    SOURCE_BINDING_VERIFICATION_FIELDS,
    SOURCE_BOUND_EVIDENCE_VERSION,
    SourceBindingDocumentError,
    load_and_validate_stored_source_binding,
)
from .checks import DEFAULT_CHECK_TIMEOUT_SECONDS
from .source_snapshot import SourceSnapshot
from .task import TASK_SCHEMA_VERSION


RUN_DOCUMENT_SCHEMA_VERSION = 1
RUN_EVIDENCE_SCHEMA_VERSION = SOURCE_BOUND_EVIDENCE_VERSION
_REQUIRED_EVIDENCE_FILES = (
    "task.json",
    "changed-files.json",
    "diff.patch",
    "checks.json",
    "verification.json",
    *SOURCE_BINDING_EVIDENCE_FILES,
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
) | SOURCE_BINDING_VERIFICATION_FIELDS
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


class RunDocumentError(ValueError):
    """Base error for internal persisted-document validation."""


class RunDocumentIdentityError(RunDocumentError):
    """Raised when persisted Task or Run identity is inconsistent."""


class RunDocumentEvidenceError(RunDocumentError):
    """Raised when persisted mechanical Evidence is inconsistent."""


@dataclass(frozen=True)
class ValidatedRunDocuments:
    """Validated persisted documents and their recomputed aggregate values."""

    changed_files: dict[str, Any]
    checks: dict[str, Any]
    verification: dict[str, Any]
    diff_patch: bytes
    check_records: tuple[dict[str, Any], ...]
    required_check_records: tuple[dict[str, Any], ...]
    log_paths: tuple[PurePosixPath, ...]
    expected_evidence_files: tuple[PurePosixPath, ...]
    source_before_checks: SourceSnapshot
    source_after_checks: SourceSnapshot
    source_stable_during_checks: bool
    scope_pass: bool
    required_checks_pass: bool
    mechanical_result: str


def validate_run_documents(
    task_id: str,
    run_id: str,
    task: Mapping[str, Any],
    evidence_path: Path,
) -> ValidatedRunDocuments:
    """Load and cross-check one Run's persisted mechanical documents."""
    evidence_task = _read_evidence_json(evidence_path, PurePosixPath("task.json"))
    changed_files = _read_evidence_json(
        evidence_path, PurePosixPath("changed-files.json")
    )
    checks = _read_evidence_json(evidence_path, PurePosixPath("checks.json"))
    verification = _read_evidence_json(
        evidence_path, PurePosixPath("verification.json")
    )
    diff_patch = _read_evidence_bytes(evidence_path, PurePosixPath("diff.patch"))

    validate_task_snapshot(evidence_task, task_id, "task.json")
    if evidence_task != task:
        raise RunDocumentIdentityError(
            f"task.json does not match saved Task snapshot '{task_id}'."
        )

    _validate_verification_document(verification)
    if verification["task_id"] != task_id:
        raise RunDocumentIdentityError(
            "verification.json task_id does not match the requested Task id."
        )
    if verification["run_id"] != run_id:
        raise RunDocumentIdentityError(
            "verification.json run_id does not match the requested run id."
        )

    evidence_files = _validate_listed_evidence_files(
        evidence_path,
        verification,
        _REQUIRED_EVIDENCE_FILES,
    )
    check_records, required_records, log_paths = _validate_check_records(
        task,
        checks,
        evidence_files,
        evidence_path,
        _REQUIRED_EVIDENCE_FILES,
    )
    computed_scope_pass = _validate_changed_files(
        task,
        changed_files,
        verification,
    )
    try:
        stored_binding = load_and_validate_stored_source_binding(
            evidence_path,
            task=task,
            changed_files=changed_files,
            verification=verification,
        )
    except SourceBindingDocumentError as error:
        raise RunDocumentEvidenceError(str(error)) from error

    computed_required_checks_pass = all(
        record["passed"] for record in required_records
    )
    computed_mechanical_result = (
        "pass"
        if computed_scope_pass
        and computed_required_checks_pass
        and stored_binding.source_stable_during_checks
        else "fail"
    )
    if verification["required_checks_pass"] != computed_required_checks_pass:
        raise RunDocumentEvidenceError(
            "verification.json required_checks_pass does not match checks.json."
        )
    if verification["mechanical_result"] != computed_mechanical_result:
        raise RunDocumentEvidenceError(
            "verification.json mechanical_result does not match saved scope and checks."
        )

    expected_evidence_files = _expected_mechanical_evidence_files(
        log_paths,
        _REQUIRED_EVIDENCE_FILES,
    )
    _validate_exact_evidence_file_list(evidence_files, expected_evidence_files)
    return ValidatedRunDocuments(
        changed_files=changed_files,
        checks=checks,
        verification=verification,
        diff_patch=diff_patch,
        check_records=tuple(check_records),
        required_check_records=tuple(required_records),
        log_paths=log_paths,
        expected_evidence_files=expected_evidence_files,
        source_before_checks=stored_binding.source_before_checks,
        source_after_checks=stored_binding.source_after_checks,
        source_stable_during_checks=stored_binding.source_stable_during_checks,
        scope_pass=computed_scope_pass,
        required_checks_pass=computed_required_checks_pass,
        mechanical_result=computed_mechanical_result,
    )


def _read_evidence_json(
    evidence_path: Path,
    relative_path: PurePosixPath,
) -> dict[str, Any]:
    try:
        value = json.loads(
            _read_evidence_bytes(evidence_path, relative_path).decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RunDocumentEvidenceError(
            f"Evidence file '{relative_path.as_posix()}' is not valid JSON."
        ) from error
    if not isinstance(value, Mapping):
        raise RunDocumentEvidenceError(
            f"Evidence file '{relative_path.as_posix()}' must be a JSON object."
        )
    return dict(value)


def _read_evidence_bytes(
    evidence_path: Path,
    relative_path: PurePosixPath,
) -> bytes:
    try:
        return read_run_artifact_bytes(evidence_path, relative_path)
    except RunArtifactReadError as error:
        if error.reason == "missing":
            message = (
                f"Required evidence file is missing: "
                f"{relative_path.as_posix()}."
            )
        elif error.reason == "unsafe":
            message = (
                f"Required evidence file is unsafe or missing: "
                f"{relative_path.as_posix()}."
            )
        else:
            message = f"Could not read evidence file: {relative_path.as_posix()}."
        raise RunDocumentEvidenceError(message) from error


def validate_task_snapshot(
    task: Mapping[str, Any],
    task_id: str,
    context: str,
) -> None:
    """Validate the Task fields required to establish stored Run identity."""
    if (
        type(task.get("schema_version")) is not int
        or task["schema_version"] != TASK_SCHEMA_VERSION
    ):
        raise RunDocumentIdentityError(
            f"{context} has an unsupported schema_version."
        )
    if task.get("id") != task_id:
        raise RunDocumentIdentityError(
            f"{context} id does not match requested Task id '{task_id}'."
        )
    if not isinstance(task.get("baseline"), str) or not task["baseline"]:
        raise RunDocumentIdentityError(
            f"{context} baseline must be a non-empty string."
        )
    _task_scope(task, context)
    _task_checks(task, context)
    verifier = task.get("verifier")
    if (
        not isinstance(verifier, Mapping)
        or type(verifier.get("required")) is not bool
    ):
        raise RunDocumentIdentityError(
            f"{context} verifier must contain a required boolean."
        )


def _task_scope(
    task: Mapping[str, Any],
    context: str,
) -> tuple[str, ...]:
    raw_scope = task.get("scope")
    if not isinstance(raw_scope, list) or not raw_scope:
        raise RunDocumentIdentityError(
            f"{context} scope must be a non-empty array."
        )
    return tuple(
        _safe_repository_relative_path(
            value,
            f"{context} scope[{index}]",
            allow_dot=True,
        )
        for index, value in enumerate(raw_scope)
    )


def _task_checks(
    task: Mapping[str, Any],
    context: str,
) -> tuple[dict[str, Any], ...]:
    raw_checks = task.get("checks")
    if not isinstance(raw_checks, list) or not raw_checks:
        raise RunDocumentIdentityError(
            f"{context} checks must be a non-empty array."
        )

    checks: list[dict[str, Any]] = []
    for index, value in enumerate(raw_checks):
        if not isinstance(value, Mapping):
            raise RunDocumentIdentityError(
                f"{context} checks[{index}] must be an object."
            )
        name = value.get("name")
        argv = value.get("argv")
        required = value.get("required")
        if not isinstance(name, str) or not name:
            raise RunDocumentIdentityError(
                f"{context} checks[{index}].name must be a non-empty string."
            )
        if (
            not isinstance(argv, list)
            or not argv
            or not all(
                isinstance(argument, str) and argument for argument in argv
            )
        ):
            raise RunDocumentIdentityError(
                f"{context} checks[{index}].argv must be a non-empty string array."
            )
        if type(required) is not bool:
            raise RunDocumentIdentityError(
                f"{context} checks[{index}].required must be a boolean."
            )
        timeout = value.get("timeout_seconds", DEFAULT_CHECK_TIMEOUT_SECONDS)
        if type(timeout) is not int or timeout <= 0:
            raise RunDocumentIdentityError(
                f"{context} checks[{index}].timeout_seconds must be a positive integer."
            )
        checks.append(dict(value))
    return tuple(checks)


def _validate_verification_document(
    verification: Mapping[str, Any],
) -> None:
    schema_version = verification.get("schema_version")
    if (
        type(schema_version) is not int
        or schema_version != RUN_EVIDENCE_SCHEMA_VERSION
    ):
        raise RunDocumentEvidenceError(
            "verification.json has an unsupported schema_version."
        )
    _require_exact_keys(verification, _VERIFICATION_FIELDS, "verification.json")
    _require_nonempty_string(
        verification.get("task_id"), "verification.json task_id"
    )
    _require_nonempty_string(
        verification.get("run_id"), "verification.json run_id"
    )
    _require_nonempty_string(
        verification.get("baseline"), "verification.json baseline"
    )
    _require_list(
        verification.get("changed_files"), "verification.json changed_files"
    )
    _require_boolean(
        verification.get("scope_pass"), "verification.json scope_pass"
    )
    _require_list(
        verification.get("scope_violations"),
        "verification.json scope_violations",
    )
    _require_boolean(
        verification.get("required_checks_pass"),
        "verification.json required_checks_pass",
    )
    mechanical_result = verification.get("mechanical_result")
    if (
        not isinstance(mechanical_result, str)
        or mechanical_result not in {"pass", "fail"}
    ):
        raise RunDocumentEvidenceError(
            "verification.json mechanical_result must be 'pass' or 'fail'."
        )
    _require_list(
        verification.get("evidence_files"),
        "verification.json evidence_files",
    )
    _require_nonempty_string(
        verification.get("timestamp"), "verification.json timestamp"
    )
    duration = verification.get("duration")
    if type(duration) not in {int, float} or duration < 0:
        raise RunDocumentEvidenceError(
            "verification.json duration must be a non-negative number."
        )
def _validate_listed_evidence_files(
    evidence_path: Path,
    verification: Mapping[str, Any],
    required_evidence_files: tuple[str, ...],
) -> dict[str, PurePosixPath]:
    raw_files = verification["evidence_files"]
    assert isinstance(raw_files, list)
    if not raw_files:
        raise RunDocumentEvidenceError(
            "verification.json evidence_files must be a non-empty array."
        )

    listed_files: dict[str, PurePosixPath] = {}
    for index, value in enumerate(raw_files):
        relative_path = _safe_evidence_relative_path(
            value,
            f"verification.json evidence_files[{index}]",
        )
        normalized = relative_path.as_posix()
        if normalized in listed_files:
            raise RunDocumentEvidenceError(
                f"verification.json evidence_files[{index}] "
                f"duplicates '{normalized}'."
            )
        listed_files[normalized] = relative_path
        _read_evidence_bytes(evidence_path, relative_path)

    missing = set(required_evidence_files) - set(listed_files)
    if missing:
        names = ", ".join(sorted(missing))
        raise RunDocumentEvidenceError(
            "verification.json evidence_files is missing required "
            f"entry(s): {names}."
        )
    return listed_files


def _expected_mechanical_evidence_files(
    log_paths: tuple[PurePosixPath, ...],
    required_evidence_files: tuple[str, ...],
) -> tuple[PurePosixPath, ...]:
    return tuple(
        PurePosixPath(path)
        for path in sorted(
            (
                *required_evidence_files,
                *(path.as_posix() for path in log_paths),
            )
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
        raise RunDocumentEvidenceError(
            "verification.json evidence_files is missing expected "
            "mechanical entry(s): "
            + ", ".join(missing)
            + "."
        )
    unexpected = sorted(listed - expected)
    raise RunDocumentEvidenceError(
        "verification.json evidence_files has unexpected non-mechanical "
        "entry(s): "
        + ", ".join(unexpected)
        + "."
    )


def _validate_check_records(
    task: Mapping[str, Any],
    checks_document: Mapping[str, Any],
    evidence_files: Mapping[str, PurePosixPath],
    evidence_path: Path,
    required_evidence_files: tuple[str, ...],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    tuple[PurePosixPath, ...],
]:
    _require_exact_keys(checks_document, _CHECKS_FIELDS, "checks.json")
    _require_schema_version(
        checks_document,
        "checks.json",
        RUN_DOCUMENT_SCHEMA_VERSION,
    )
    recorded_checks = checks_document.get("checks")
    if not isinstance(recorded_checks, list):
        raise RunDocumentEvidenceError("checks.json checks must be an array.")

    task_checks = _task_checks(task, "saved Task snapshot")
    if len(recorded_checks) != len(task_checks):
        raise RunDocumentEvidenceError(
            "checks.json does not contain one result for every Task check."
        )

    records: list[dict[str, Any]] = []
    required_records: list[dict[str, Any]] = []
    log_paths: list[PurePosixPath] = []
    seen_log_paths = set(required_evidence_files)
    for index, (task_check, recorded_check) in enumerate(
        zip(task_checks, recorded_checks)
    ):
        context = f"checks.json checks[{index}]"
        if not isinstance(recorded_check, Mapping):
            raise RunDocumentEvidenceError(f"{context} must be an object.")
        _require_exact_keys(recorded_check, _CHECK_RECORD_FIELDS, context)
        record = dict(recorded_check)
        for field in ("name", "argv", "required"):
            if record[field] != task_check[field]:
                raise RunDocumentEvidenceError(
                    f"{context}.{field} does not match saved "
                    f"Task check[{index}].{field}."
                )

        _require_nonempty_string(record.get("cwd"), f"{context}.cwd")
        _require_nonempty_string(
            record.get("started_at"), f"{context}.started_at"
        )
        _require_nonempty_string(
            record.get("finished_at"), f"{context}.finished_at"
        )
        duration = record.get("duration_seconds")
        if type(duration) not in {int, float} or duration < 0:
            raise RunDocumentEvidenceError(
                f"{context}.duration_seconds must be a non-negative number."
            )
        expected_timeout = task_check.get(
            "timeout_seconds",
            DEFAULT_CHECK_TIMEOUT_SECONDS,
        )
        if record.get("effective_timeout") != expected_timeout:
            raise RunDocumentEvidenceError(
                f"{context}.effective_timeout does not match saved "
                f"Task check[{index}]."
            )

        passed = record.get("passed")
        timed_out = record.get("timed_out")
        exit_code = record.get("exit_code")
        if type(passed) is not bool:
            raise RunDocumentEvidenceError(
                f"{context}.passed must be a boolean."
            )
        if type(timed_out) is not bool:
            raise RunDocumentEvidenceError(
                f"{context}.timed_out must be a boolean."
            )
        if exit_code is not None and type(exit_code) is not int:
            raise RunDocumentEvidenceError(
                f"{context}.exit_code must be an integer or null."
            )
        if passed != (not timed_out and exit_code == 0):
            raise RunDocumentEvidenceError(
                f"{context}.passed does not match timed_out and exit_code."
            )

        for field in ("stdout_path", "stderr_path"):
            relative_path = _safe_evidence_relative_path(
                record.get(field),
                f"{context}.{field}",
            )
            normalized = relative_path.as_posix()
            if normalized not in evidence_files:
                raise RunDocumentEvidenceError(
                    f"{context}.{field} is not listed in "
                    "verification.json evidence_files."
                )
            if normalized in seen_log_paths:
                raise RunDocumentEvidenceError(
                    f"{context}.{field} duplicates an existing "
                    f"evidence path '{normalized}'."
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
    _require_exact_keys(
        changed_files,
        _CHANGED_FILES_FIELDS,
        "changed-files.json",
    )
    _require_schema_version(
        changed_files,
        "changed-files.json",
        RUN_DOCUMENT_SCHEMA_VERSION,
    )
    baseline = _require_nonempty_string(
        changed_files.get("baseline"),
        "changed-files.json baseline",
    )
    if baseline != verification["baseline"]:
        raise RunDocumentEvidenceError(
            "changed-files.json baseline does not match "
            "verification.json baseline."
        )

    task_scope = _task_scope(task, "saved Task snapshot")
    raw_scope = changed_files.get("scope")
    if not isinstance(raw_scope, list):
        raise RunDocumentEvidenceError(
            "changed-files.json scope must be an array."
        )
    recorded_scope = tuple(
        _safe_repository_relative_path(
            value,
            f"changed-files.json scope[{index}]",
            allow_dot=True,
        )
        for index, value in enumerate(raw_scope)
    )
    if recorded_scope != task_scope:
        raise RunDocumentEvidenceError(
            "changed-files.json scope does not match saved Task scope."
        )

    raw_changes = changed_files.get("changes")
    if not isinstance(raw_changes, list):
        raise RunDocumentEvidenceError(
            "changed-files.json changes must be an array."
        )
    changes = [
        _validate_file_change(
            value,
            f"changed-files.json changes[{index}]",
            task_scope,
        )
        for index, value in enumerate(raw_changes)
    ]
    product_changes = [
        change for change in changes if not _is_seal_metadata_change(change)
    ]
    expected_violations = [
        change for change in product_changes if not change["in_scope"]
    ]

    recorded_product_changes = verification["changed_files"]
    assert isinstance(recorded_product_changes, list)
    if recorded_product_changes != product_changes:
        raise RunDocumentEvidenceError(
            "verification.json changed_files does not match product "
            "changes in changed-files.json."
        )
    recorded_violations = verification["scope_violations"]
    assert isinstance(recorded_violations, list)
    if recorded_violations != expected_violations:
        raise RunDocumentEvidenceError(
            "verification.json scope_violations does not match "
            "out-of-scope product changes."
        )

    computed_scope_pass = not expected_violations
    if verification["scope_pass"] != computed_scope_pass:
        raise RunDocumentEvidenceError(
            "verification.json scope_pass does not match scope_violations."
        )
    return computed_scope_pass


def _validate_file_change(
    value: object,
    context: str,
    scope: tuple[str, ...],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RunDocumentEvidenceError(f"{context} must be an object.")
    _require_exact_keys(value, _FILE_CHANGE_FIELDS, context)
    source = value.get("source")
    if not isinstance(source, str) or source not in _CHANGE_SOURCES:
        raise RunDocumentEvidenceError(f"{context}.source is invalid.")
    status = _require_nonempty_string(value.get("status"), f"{context}.status")
    path = _safe_repository_relative_path(
        value.get("path"),
        f"{context}.path",
    )
    previous_value = value.get("previous_path")
    previous_path = (
        None
        if previous_value is None
        else _safe_repository_relative_path(
            previous_value,
            f"{context}.previous_path",
        )
    )
    for field in ("old_mode", "new_mode"):
        mode = value.get(field)
        if mode is not None and (not isinstance(mode, str) or not mode):
            raise RunDocumentEvidenceError(
                f"{context}.{field} must be a non-empty string or null."
            )
    for field in ("mode_changed", "is_binary", "in_scope"):
        _require_boolean(value.get(field), f"{context}.{field}")

    expected_in_scope = _change_is_within_scope(
        status=status,
        path=path,
        previous_path=previous_path,
        scope=scope,
    )
    if value["in_scope"] != expected_in_scope:
        raise RunDocumentEvidenceError(
            f"{context}.in_scope does not match saved Task scope."
        )
    return dict(value)


def _is_seal_metadata_change(change: Mapping[str, Any]) -> bool:
    paths = [change["path"]]
    previous_path = change["previous_path"]
    if previous_path is not None:
        paths.append(previous_path)
    return all(_is_seal_metadata_path(path) for path in paths)


def _safe_evidence_relative_path(
    value: object,
    context: str,
) -> PurePosixPath:
    try:
        return safe_run_relative_path(value, context)
    except RunArtifactPathError as error:
        raise RunDocumentEvidenceError(str(error)) from error


def _safe_repository_relative_path(
    value: object,
    context: str,
    *,
    allow_dot: bool = False,
) -> str:
    if not isinstance(value, str) or not value:
        raise RunDocumentEvidenceError(
            f"{context} must be a non-empty repository-relative path."
        )
    if allow_dot and value == ".":
        return value
    if "\\" in value or "\x00" in value:
        raise RunDocumentEvidenceError(
            f"{context} must use a repository-relative POSIX path."
        )
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
        raise RunDocumentEvidenceError(
            f"{context} must be a repository-relative path."
        )
    return path.as_posix()


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: frozenset[str],
    context: str,
) -> None:
    missing = expected - set(value)
    unexpected = set(value) - expected
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unexpected:
            details.append("unexpected " + ", ".join(sorted(unexpected)))
        raise RunDocumentEvidenceError(
            f"{context} has " + "; ".join(details) + " field(s)."
        )


def _require_schema_version(
    document: Mapping[str, Any],
    filename: str,
    expected_version: int,
) -> None:
    if (
        type(document.get("schema_version")) is not int
        or document["schema_version"] != expected_version
    ):
        raise RunDocumentEvidenceError(
            f"{filename} has an unsupported schema_version."
        )


def _require_nonempty_string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise RunDocumentEvidenceError(
            f"{context} must be a non-empty string."
        )
    return value


def _require_boolean(value: object, context: str) -> bool:
    if type(value) is not bool:
        raise RunDocumentEvidenceError(f"{context} must be a boolean.")
    return value


def _require_list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise RunDocumentEvidenceError(f"{context} must be an array.")
    return value
