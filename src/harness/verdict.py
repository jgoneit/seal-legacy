"""Manual verifier Verdict parsing, storage, and retrieval.

This module records a supplied Manual Verdict for one already-saved
verification run. It does not invoke a model, call a network service, rerun
checks, or decide mechanical verification.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ._run_artifact_io import (
    RunArtifactReadError as _RunArtifactReadError,
    atomic_write_bytes as _atomic_write_run_bytes,
    read_run_artifact_bytes as _read_run_artifact_bytes,
)
from .run_validator import (
    RUN_ID_CHARACTERS,
    RunIdentityError,
    RunValidationError,
    validate_run,
    validate_run_id as _validate_run_id,
)
from .task import TaskError, validate_task_id
from .verdict_validator import VerdictValidationError, finding_severities, validate_verdict


RAW_VERDICT_FILENAME = "verdict.raw.json"
VERDICT_FILENAME = "verdict.json"


class VerdictError(TaskError):
    """Base error for Manual Verdict operations."""


class VerdictInputError(VerdictError):
    """Raised when a requested Verdict or command identity is invalid."""


class VerdictEvidenceError(VerdictError):
    """Raised when saved Verdict evidence is absent, corrupt, or inconsistent."""


@dataclass(frozen=True)
class VerdictRecord:
    """One validated Verdict and its preserved raw source file."""

    task_id: str
    run_id: str
    verdict: dict[str, Any]
    counts: dict[str, int]
    raw_path: Path
    snapshot_path: Path


def record_verdict(
    task_id: str,
    run_id: str,
    verdict_file: str | Path,
    *,
    cwd: str | Path | None = None,
) -> VerdictRecord:
    """Validate and atomically store one Manual Verdict for a saved Task run."""
    try:
        validated_run = validate_run(task_id, run_id, cwd=cwd)
    except RunIdentityError as error:
        raise VerdictInputError(str(error)) from error
    except RunValidationError as error:
        raise VerdictEvidenceError(str(error)) from error
    evidence_path = validated_run.evidence_path

    source_path = Path(verdict_file)
    raw_bytes = _read_source_bytes(source_path)
    snapshot = _parse_verdict_bytes(
        raw_bytes,
        f"Verdict file '{source_path}'",
        persisted=False,
        expected_task_id=task_id,
        expected_run_id=run_id,
    )

    raw_path = evidence_path / RAW_VERDICT_FILENAME
    snapshot_path = evidence_path / VERDICT_FILENAME
    _atomic_write_run_bytes(raw_path, raw_bytes)
    _atomic_write_json(snapshot_path, snapshot)
    return VerdictRecord(
        task_id=task_id,
        run_id=run_id,
        verdict=snapshot,
        counts=count_findings(snapshot),
        raw_path=raw_path,
        snapshot_path=snapshot_path,
    )


def show_verdict(
    task_id: str,
    run_id: str,
    *,
    cwd: str | Path | None = None,
) -> VerdictRecord:
    """Load one recorded Verdict after validating the Task/run identity."""
    try:
        validated_run = validate_run(task_id, run_id, cwd=cwd)
    except RunIdentityError as error:
        raise VerdictInputError(str(error)) from error
    except RunValidationError as error:
        raise VerdictEvidenceError(str(error)) from error
    evidence_path = validated_run.evidence_path
    record = load_recorded_verdict(evidence_path, task_id, run_id)
    if record is None:
        raise VerdictEvidenceError(
            "No Manual Verifier Verdict has been recorded for the requested Task run."
        )
    return record


def load_recorded_verdict(
    evidence_path: str | Path,
    task_id: str,
    run_id: str,
) -> VerdictRecord | None:
    """Load consistent raw and canonical Verdict files, or return None if absent.

    A partially-written or malformed record is never interpreted as a passing
    Verdict. The raw source is parsed again and must validate to exactly the
    saved canonical snapshot before it can influence completion.
    """
    validate_task_id(task_id)
    validate_run_id(run_id)
    directory = Path(evidence_path)
    raw_path = directory / RAW_VERDICT_FILENAME
    snapshot_path = directory / VERDICT_FILENAME
    raw_bytes = _read_optional_evidence_bytes(
        directory,
        PurePosixPath(RAW_VERDICT_FILENAME),
    )
    snapshot_bytes = _read_optional_evidence_bytes(
        directory,
        PurePosixPath(VERDICT_FILENAME),
    )
    if raw_bytes is None and snapshot_bytes is None:
        return None
    if raw_bytes is None or snapshot_bytes is None:
        raise VerdictEvidenceError(
            "Manual Verdict evidence must include both raw and canonical Verdict files."
        )

    raw = _parse_verdict_bytes(
        raw_bytes,
        RAW_VERDICT_FILENAME,
        persisted=True,
        expected_task_id=task_id,
        expected_run_id=run_id,
    )
    snapshot = _parse_verdict_bytes(
        snapshot_bytes,
        VERDICT_FILENAME,
        persisted=True,
        expected_task_id=task_id,
        expected_run_id=run_id,
    )
    if raw != snapshot:
        raise VerdictEvidenceError(
            "Manual Verdict raw source does not match its canonical snapshot."
        )

    return VerdictRecord(
        task_id=task_id,
        run_id=run_id,
        verdict=snapshot,
        counts=count_findings(snapshot),
        raw_path=raw_path,
        snapshot_path=snapshot_path,
    )


def count_findings(verdict: Mapping[str, Any]) -> dict[str, int]:
    """Return counts for the severities declared by the packaged Schema."""
    findings = verdict.get("findings")
    if not isinstance(findings, list):
        raise VerdictEvidenceError("Validated Verdict findings must be an array.")
    counts = empty_finding_counts()
    for finding in findings:
        if not isinstance(finding, Mapping):
            raise VerdictEvidenceError("Validated Verdict contains an invalid finding.")
        severity = finding.get("severity")
        if not isinstance(severity, str):
            raise VerdictEvidenceError("Validated Verdict contains an invalid finding severity.")
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def empty_finding_counts() -> dict[str, int]:
    """Return zero counts for the severities declared by the packaged Schema."""
    try:
        return {severity: 0 for severity in finding_severities()}
    except VerdictValidationError as error:
        raise VerdictEvidenceError("Could not load Verdict severity definitions.") from error


def validate_run_id(run_id: object) -> str:
    """Validate a path-safe verification run identifier."""
    try:
        return _validate_run_id(run_id)
    except RunIdentityError as error:
        raise VerdictInputError(str(error)) from error


def _read_source_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise VerdictInputError(f"Could not read Verdict file: {path}.") from error


def _read_optional_evidence_bytes(
    directory: Path,
    relative_path: PurePosixPath,
) -> bytes | None:
    try:
        return _read_run_artifact_bytes(directory, relative_path)
    except _RunArtifactReadError as error:
        if error.reason == "missing":
            return None
        if error.reason == "unsafe":
            message = (
                "Required Verdict evidence file is unsafe or missing: "
                f"{relative_path.as_posix()}."
            )
        else:
            message = (
                "Could not read Verdict evidence file: "
                f"{relative_path.as_posix()}."
            )
        raise VerdictEvidenceError(
            message
        ) from error


def _parse_verdict_bytes(
    raw: bytes,
    description: str,
    *,
    persisted: bool,
    expected_task_id: str,
    expected_run_id: str,
) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        error_type = VerdictEvidenceError if persisted else VerdictInputError
        raise error_type(f"{description} is not valid JSON.") from error
    try:
        return validate_verdict(
            value,
            expected_task_id=expected_task_id,
            expected_run_id=expected_run_id,
        )
    except VerdictValidationError as error:
        error_type = VerdictEvidenceError if persisted else VerdictInputError
        raise error_type(str(error)) from error


def _atomic_write_json(path: Path, value: object) -> None:
    contents = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    _atomic_write_run_bytes(path, f"{contents}\n".encode("utf-8"))
