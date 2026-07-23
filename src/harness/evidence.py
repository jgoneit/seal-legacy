"""Mechanical verification Evidence creation for Outcome Harness.

This module records checks, Git changes, and versioned Run artifacts.  The
completion policy is implemented behind a separate internal boundary while
its established public imports remain available here.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from ._completion import (
    COMPLETION_SCHEMA_VERSION,
    CompletionError,
    CompletionEvidenceError,
    CompletionInputError,
    CompletionRequiredCheckFailureError,
    CompletionRun,
    CompletionScopeViolationError,
    CompletionTimeoutError,
    CompletionVerifierEvidenceMissingError,
    CompletionVerifierRejectedError,
    EvidenceError,
    complete_task,
)
from ._run_artifact_io import (
    atomic_write as _atomic_write,
    atomic_write_bytes,
    atomic_write_json,
)
from ._source_binding_documents import (
    SOURCE_AFTER_CHECKS_FILENAME,
    SOURCE_AFTER_CHECKS_SHA256_FIELD,
    SOURCE_BEFORE_CHECKS_FILENAME,
    SOURCE_BEFORE_CHECKS_SHA256_FIELD,
    SOURCE_BOUND_EVIDENCE_VERSION,
    SOURCE_SNAPSHOT_SCHEMA_VERSION_FIELD,
    SOURCE_STABLE_DURING_CHECKS_FIELD,
)
from .checks import CheckExecutionError, run_checks
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
from .source_snapshot import SourceSnapshotError, collect_source_snapshot
from .task import show_task, validate_task_id


RUN_DOCUMENT_SCHEMA_VERSION = 1
VERIFICATION_SCHEMA_VERSION = SOURCE_BOUND_EVIDENCE_VERSION


class EvidenceRepositoryError(EvidenceError):
    """Raised when repository state cannot be collected or persisted safely."""


@dataclass(frozen=True)
class VerificationRun:
    """The identity, location, and final document for one verification run."""

    run_id: str
    evidence_path: Path
    verification: dict[str, Any]


def verify_task(
    task_id: str,
    *,
    cwd: str | Path | None = None,
) -> VerificationRun:
    """Run a saved Task's checks and persist its mechanical evidence.

    Check failures are evidence, not CLI errors: all checks run in Task Spec
    order and the resulting mechanical pass/fail is written to
    ``verification.json``.
    """
    validate_task_id(task_id)
    repository = find_repository_root(cwd)
    task = show_task(task_id, cwd=repository)
    started = time.monotonic()

    try:
        source_before_checks = collect_source_snapshot(task, cwd=repository)
        run_id, evidence_path = create_evidence_directory(repository, task_id)
        atomic_write_json(evidence_path / "task.json", task)
        checks = task.get("checks")
        if not isinstance(checks, list):
            raise EvidenceError("Task snapshot checks must be an array.")
        check_results = run_checks(
            checks,
            cwd=repository,
            evidence_directory=evidence_path,
        )
        source_after_checks = collect_source_snapshot(task, cwd=repository)
        source_stable_during_checks = source_before_checks == source_after_checks
        atomic_write_json(
            evidence_path / SOURCE_BEFORE_CHECKS_FILENAME,
            source_before_checks.to_document(),
        )
        atomic_write_json(
            evidence_path / SOURCE_AFTER_CHECKS_FILENAME,
            source_after_checks.to_document(),
        )

        changes = collect_changes(task, cwd=repository)
        changed_files = [_file_change_document(change) for change in changes.product_changes]
        scope_violations = [
            _file_change_document(change) for change in changes.out_of_scope_changes
        ]
        atomic_write_json(
            evidence_path / "changed-files.json",
            _changed_files_document(changes),
        )
        write_diff_patch(evidence_path / "diff.patch", repository, changes)
        atomic_write_json(
            evidence_path / "checks.json",
            {"schema_version": RUN_DOCUMENT_SCHEMA_VERSION, "checks": check_results},
        )

        required_checks_pass = all(
            bool(result["passed"])
            for result in check_results
            if bool(result["required"])
        )
        scope_pass = changes.scope_passed
        mechanical_result = (
            "pass"
            if scope_pass
            and required_checks_pass
            and source_stable_during_checks
            else "fail"
        )
        evidence_files = _evidence_file_list(check_results)
        verification = {
            "schema_version": VERIFICATION_SCHEMA_VERSION,
            "task_id": task_id,
            "run_id": run_id,
            "baseline": changes.baseline,
            "changed_files": changed_files,
            "scope_pass": scope_pass,
            "scope_violations": scope_violations,
            "required_checks_pass": required_checks_pass,
            SOURCE_SNAPSHOT_SCHEMA_VERSION_FIELD: (
                source_before_checks.schema_version
            ),
            SOURCE_BEFORE_CHECKS_SHA256_FIELD: (
                source_before_checks.snapshot_sha256
            ),
            SOURCE_AFTER_CHECKS_SHA256_FIELD: source_after_checks.snapshot_sha256,
            SOURCE_STABLE_DURING_CHECKS_FIELD: source_stable_during_checks,
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
            raise EvidenceRepositoryError(
                f"Could not create run manifest for Evidence Run '{evidence_path}': {error}"
            ) from error
    except GitDiffTaskError as error:
        raise EvidenceError(str(error)) from error
    except GitDiffError as error:
        raise EvidenceRepositoryError(str(error)) from error
    except SourceSnapshotError as error:
        raise EvidenceRepositoryError(str(error)) from error
    except OSError as error:
        raise EvidenceRepositoryError(
            f"Could not persist verification Evidence: {error}"
        ) from error
    except CheckExecutionError as error:
        raise EvidenceError(str(error)) from error

    return VerificationRun(
        run_id=run_id,
        evidence_path=evidence_path,
        verification=verification,
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


def write_diff_patch(
    path: str | Path,
    repository: str | Path,
    changes: ChangeCollection,
) -> None:
    """Atomically stream a binary-safe patch for every product change layer."""
    repository_path = Path(repository).resolve()

    def write(output: BinaryIO) -> None:
        _write_diff_patch(output, repository_path, changes)

    _atomic_write(Path(path), mode="wb", writer=write)


def _write_diff_patch(
    output: BinaryIO,
    repository: Path,
    changes: ChangeCollection,
) -> None:
    """Write committed, staged, unstaged, and untracked patches in order."""
    prefix = [
        "git",
        "-C",
        str(repository),
        "diff",
        "--binary",
        "--no-ext-diff",
        "--no-textconv",
    ]
    pathspecs = ["--", ".", *_metadata_exclude_pathspecs()]
    commands: list[tuple[list[str], set[int]]] = [
        ([*prefix, changes.baseline, "HEAD", *pathspecs], {0}),
        ([*prefix, "--cached", *pathspecs], {0}),
        ([*prefix, *pathspecs], {0}),
    ]
    commands.extend(
        (
            [
                *prefix,
                "--no-index",
                "--",
                "/dev/null",
                change.path,
            ],
            {0, 1},
        )
        for change in changes.changes
        if change.source == "untracked" and not is_harness_metadata_path(change.path)
    )

    wrote_patch = False
    for arguments, accepted_returncodes in commands:
        separator_position = _output_offset(output)
        if wrote_patch:
            output.write(b"\n")
        wrote_segment = _stream_git(
            arguments,
            output,
            accepted_returncodes=accepted_returncodes,
        )
        if wrote_segment:
            wrote_patch = True
        elif wrote_patch:
            output.truncate(separator_position)
            output.seek(separator_position)


def _stream_git(
    arguments: list[str],
    output: BinaryIO,
    *,
    accepted_returncodes: set[int],
) -> bool:
    """Stream Git stdout into *output* without retaining a patch in memory."""
    start_position = _output_offset(output)
    try:
        with tempfile.TemporaryFile(mode="w+b") as stderr:
            result = subprocess.run(
                arguments,
                check=False,
                stdout=output,
                stderr=stderr,
                shell=False,
            )
            end_position = _output_offset(output)
            if result.returncode not in accepted_returncodes:
                stderr.seek(0)
                detail = stderr.read(8192).decode("utf-8", "replace").strip()
                raise EvidenceRepositoryError(
                    detail or f"Git diff exited with status {result.returncode}."
                )
    except OSError as error:
        raise EvidenceRepositoryError(
            "Git is required to write verification evidence."
        ) from error
    return end_position > start_position


def _output_offset(output: BinaryIO) -> int:
    output.flush()
    return os.lseek(output.fileno(), 0, os.SEEK_CUR)


def _metadata_exclude_pathspecs() -> tuple[str, ...]:
    directories = tuple(f":(exclude){path}/**" for path in HARNESS_METADATA_DIRECTORIES)
    files = tuple(f":(exclude){path}" for path in sorted(HARNESS_METADATA_FILES))
    return directories + files


def _changed_files_document(changes: ChangeCollection) -> dict[str, Any]:
    return {
        "schema_version": RUN_DOCUMENT_SCHEMA_VERSION,
        "baseline": changes.baseline,
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
    files = [
        "task.json",
        SOURCE_BEFORE_CHECKS_FILENAME,
        SOURCE_AFTER_CHECKS_FILENAME,
        "changed-files.json",
        "diff.patch",
        "checks.json",
    ]
    for result in check_results:
        files.extend((str(result["stdout_path"]), str(result["stderr_path"])))
    files.append("verification.json")
    return files


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
