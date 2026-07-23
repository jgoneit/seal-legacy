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
from pathlib import Path, PurePosixPath
from typing import Any

from ._run_documents import (
    RUN_EVIDENCE_SCHEMA_VERSION,
    RunDocumentEvidenceError as _RunDocumentEvidenceError,
    RunDocumentIdentityError as _RunDocumentIdentityError,
    validate_run_documents as _validate_run_documents,
    validate_task_snapshot as _validate_task_snapshot,
)
from .run_manifest import RunManifestError, load_and_validate_run_manifest
from .source_snapshot import SourceSnapshot
from .task import TaskError, TaskRepositoryError, validate_task_id


RUN_ID_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
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

    evidence_version: int
    source_before_checks: SourceSnapshot | None
    source_after_checks: SourceSnapshot | None
    source_stable_during_checks: bool | None
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
    try:
        _validate_task_snapshot(task, task_id, "saved Task snapshot")
    except _RunDocumentIdentityError as error:
        raise RunIdentityError(str(error)) from error
    except _RunDocumentEvidenceError as error:
        raise RunEvidenceError(str(error)) from error

    evidence_path = _validated_evidence_directory(repository, task_id, run_id)
    try:
        documents = _validate_run_documents(
            task_id,
            run_id,
            task,
            evidence_path,
        )
    except _RunDocumentIdentityError as error:
        raise RunIdentityError(str(error)) from error
    except _RunDocumentEvidenceError as error:
        raise RunEvidenceError(str(error)) from error

    try:
        manifest = load_and_validate_run_manifest(
            evidence_path,
            expected_task_id=task_id,
            expected_run_id=run_id,
            expected_files=documents.expected_evidence_files,
        )
    except RunManifestError as error:
        raise RunEvidenceError(str(error)) from error

    return ValidatedRun(
        repository=repository,
        task_id=task_id,
        run_id=run_id,
        evidence_path=evidence_path,
        task=_freeze_json(task),
        changed_files=_freeze_json(documents.changed_files),
        checks=_freeze_json(documents.checks),
        verification=_freeze_json(documents.verification),
        diff_patch=bytes(documents.diff_patch),
        check_records=tuple(
            _freeze_json(record) for record in documents.check_records
        ),
        required_check_records=tuple(
            _freeze_json(record)
            for record in documents.required_check_records
        ),
        log_paths=tuple(documents.log_paths),
        evidence_sha256=manifest.evidence_sha256,
        evidence_version=documents.evidence_version,
        source_before_checks=documents.source_before_checks,
        source_after_checks=documents.source_after_checks,
        source_stable_during_checks=documents.source_stable_during_checks,
        scope_pass=documents.scope_pass,
        required_checks_pass=documents.required_checks_pass,
        mechanical_result=documents.mechanical_result,
    )


def _freeze_json(value: Any) -> Any:
    """Create a deep, JSON-compatible immutable snapshot without aliases."""
    if isinstance(value, Mapping):
        frozen = _FrozenDict()
        for key, item in value.items():
            dict.__setitem__(
                frozen,
                copy.deepcopy(key),
                _freeze_json(item),
            )
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
        raise TaskRepositoryError(
            "Task commands must run inside a Git repository."
        ) from error
    start = resolved if resolved.is_dir() else resolved.parent
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise TaskRepositoryError("Task commands must run inside a Git repository.")


def _read_saved_task_snapshot(
    repository: Path,
    task_id: str,
) -> dict[str, Any]:
    path = repository / ".harness" / "tasks" / f"{task_id}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RunIdentityError(
            f"Saved Task snapshot '{task_id}' does not exist."
        ) from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RunIdentityError(
            f"Saved Task snapshot '{task_id}' is unreadable or invalid JSON."
        ) from error
    if not isinstance(value, Mapping):
        raise RunIdentityError(
            f"Saved Task snapshot '{task_id}' must be a JSON object."
        )
    return dict(value)


def _validated_evidence_directory(
    repository: Path,
    task_id: str,
    run_id: str,
) -> Path:
    logical_path = (
        repository / ".harness" / "evidence" / task_id / run_id
    )
    try:
        evidence_directories = (
            repository / ".harness",
            repository / ".harness" / "evidence",
            repository / ".harness" / "evidence" / task_id,
            logical_path,
        )
        if (
            any(path.is_symlink() for path in evidence_directories)
            or not logical_path.is_dir()
        ):
            raise RunEvidenceError(
                "Evidence Run directory is missing or unsafe: "
                f"{task_id}/{run_id}."
            )
        evidence_path = logical_path.resolve(strict=True)
    except OSError as error:
        raise RunEvidenceError(
            "Evidence Run directory is missing or unreadable: "
            f"{task_id}/{run_id}."
        ) from error

    if not evidence_path.is_relative_to(repository.resolve()):
        raise RunEvidenceError(
            "Evidence Run directory must remain inside the repository."
        )
    return evidence_path
