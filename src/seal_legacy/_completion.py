"""Internal completion policy for one canonically validated Evidence Run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._run_artifact_io import atomic_write_json
from ._source_binding import (
    SourceBindingCollectionError,
    SourceBindingNotSatisfiedError,
    evaluate_completion_source_binding,
)
from .exit_codes import ExitCode
from .run_validator import RunIdentityError, RunValidationError, validate_run
from .task import TaskError
from .verdict import (
    VerdictEvidenceError,
    empty_finding_counts,
    load_recorded_verdict,
)


COMPLETION_SCHEMA_VERSION = 1


class EvidenceError(TaskError):
    """Raised when Seal Legacy cannot safely create or consume Run Evidence."""


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


class CompletionSourceCollectionError(CompletionError):
    """Raised when current product source cannot be observed safely."""

    exit_code = ExitCode.GIT_OR_REPOSITORY_ERROR


class CompletionSourceBindingError(CompletionError):
    """Raised when Evidence cannot support the current-source claim."""

    exit_code = ExitCode.SOURCE_BINDING_NOT_SATISFIED


@dataclass(frozen=True)
class CompletionRun:
    """The immutable completion record written for one successful evidence run."""

    task_id: str
    run_id: str
    completion_path: Path
    completion: dict[str, Any]


def complete_task(
    task_id: str,
    run_id: str,
    *,
    cwd: str | Path | None = None,
) -> CompletionRun:
    """Validate saved mechanical and verifier evidence and write completion.

    Completion never reruns checks, recalculates the recorded Git diff, or
    chooses a latest run.  It collects only the current canonical source
    Snapshot needed to bind the supplied Task/run pair.
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
        verdict_record = load_recorded_verdict(
            evidence_path,
            task_id,
            run_id,
        )
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
    if verdict_record is not None:
        verifier = verdict_record.verdict["verifier"]
        verifier_runner = verifier["runner"]
        verifier_verdict = verdict_record.verdict["verdict"]
        finding_counts = verdict_record.counts

    try:
        evaluate_completion_source_binding(validated_run)
    except SourceBindingCollectionError as error:
        raise CompletionSourceCollectionError(str(error)) from error
    except SourceBindingNotSatisfiedError as error:
        raise CompletionSourceBindingError(str(error)) from error

    if verdict_record is None:
        if verifier_required:
            raise CompletionVerifierEvidenceMissingError(
                "Task requires a valid manual verifier verdict, "
                "but no verdict was recorded."
            )
    else:
        if verifier_verdict != "pass":
            raise CompletionVerifierRejectedError(
                "Completion rejected because the recorded verifier "
                "verdict is not pass."
            )
        if finding_counts["blocker"] > 0:
            raise CompletionVerifierRejectedError(
                "Completion rejected because the recorded verifier "
                "verdict has blocker findings."
            )
    if not validated_run.scope_pass:
        raise CompletionScopeViolationError(
            "Completion rejected because saved evidence contains "
            "a Scope violation."
        )
    if any(
        record["timed_out"]
        for record in validated_run.required_check_records
    ):
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


def _task_requires_verifier(task: Mapping[str, Any]) -> bool:
    verifier = task.get("verifier")
    if (
        not isinstance(verifier, Mapping)
        or type(verifier.get("required")) is not bool
    ):
        raise CompletionInputError(
            "Saved Task snapshot verifier must contain required boolean."
        )
    return bool(verifier["required"])


def _utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
