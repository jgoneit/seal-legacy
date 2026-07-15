"""Manual verifier verdict parsing, storage, and retrieval.

This module only records a supplied manual verdict for one already-saved
verification run. It does not invoke a model, call a network service, rerun
checks, or decide mechanical verification.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .task import TaskError, find_repository_root, show_task, validate_task_id


VERDICT_SCHEMA_VERSION = 1
RAW_VERDICT_FILENAME = "verdict.raw.json"
VERDICT_FILENAME = "verdict.json"
VERDICTS = frozenset({"pass", "fail", "unable"})
SEVERITIES = frozenset({"blocker", "warning", "note"})
RUN_ID_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)


class VerdictError(TaskError):
    """Base error for manual verifier verdict operations."""


class VerdictInputError(VerdictError):
    """Raised when a requested verdict or command identity is invalid."""


class VerdictEvidenceError(VerdictError):
    """Raised when saved verdict evidence is absent, corrupt, or inconsistent."""


@dataclass(frozen=True)
class VerdictRecord:
    """One normalized verdict and its preserved raw source file."""

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
    """Validate and atomically store one manual verdict for a saved Task run."""
    validate_task_id(task_id)
    validate_run_id(run_id)
    repository = find_repository_root(cwd)
    show_task(task_id, cwd=repository)
    evidence_path = _evidence_path(repository, task_id, run_id)
    _validate_saved_run_identity(evidence_path, task_id, run_id)

    source_path = Path(verdict_file)
    raw_bytes = _read_source_bytes(source_path)
    normalized = _parse_verdict_bytes(
        raw_bytes,
        f"Verdict file '{source_path}'",
        persisted=False,
    )
    _assert_verdict_identity(normalized, task_id, run_id, persisted=False)

    raw_path = evidence_path / RAW_VERDICT_FILENAME
    snapshot_path = evidence_path / VERDICT_FILENAME
    _atomic_write_bytes(raw_path, raw_bytes)
    _atomic_write_json(snapshot_path, normalized)
    return VerdictRecord(
        task_id=task_id,
        run_id=run_id,
        verdict=normalized,
        counts=count_findings(normalized),
        raw_path=raw_path,
        snapshot_path=snapshot_path,
    )


def show_verdict(
    task_id: str,
    run_id: str,
    *,
    cwd: str | Path | None = None,
) -> VerdictRecord:
    """Load one recorded verdict after validating the Task/run identity."""
    validate_task_id(task_id)
    validate_run_id(run_id)
    repository = find_repository_root(cwd)
    show_task(task_id, cwd=repository)
    evidence_path = _evidence_path(repository, task_id, run_id)
    _validate_saved_run_identity(evidence_path, task_id, run_id)
    record = load_recorded_verdict(evidence_path, task_id, run_id)
    if record is None:
        raise VerdictEvidenceError(
            "No manual verifier verdict has been recorded for the requested Task run."
        )
    return record


def load_recorded_verdict(
    evidence_path: str | Path,
    task_id: str,
    run_id: str,
) -> VerdictRecord | None:
    """Load consistent raw and normalized verdict files, or return None if absent.

    A partially-written or malformed record is never interpreted as a passing
    verdict. The raw source is parsed again and must normalize to exactly the
    saved snapshot before it can influence completion.
    """
    validate_task_id(task_id)
    validate_run_id(run_id)
    directory = Path(evidence_path)
    raw_path = directory / RAW_VERDICT_FILENAME
    snapshot_path = directory / VERDICT_FILENAME
    raw_exists = raw_path.is_file()
    snapshot_exists = snapshot_path.is_file()
    if not raw_exists and not snapshot_exists:
        return None
    if not raw_exists or not snapshot_exists:
        raise VerdictEvidenceError(
            "Manual verdict evidence must include both raw and normalized verdict files."
        )

    raw = _parse_verdict_bytes(
        _read_evidence_bytes(raw_path),
        RAW_VERDICT_FILENAME,
        persisted=True,
    )
    snapshot = _parse_verdict_bytes(
        _read_evidence_bytes(snapshot_path),
        VERDICT_FILENAME,
        persisted=True,
    )
    _assert_verdict_identity(raw, task_id, run_id, persisted=True)
    _assert_verdict_identity(snapshot, task_id, run_id, persisted=True)
    if raw != snapshot:
        raise VerdictEvidenceError(
            "Manual verdict raw source does not match its normalized snapshot."
        )

    return VerdictRecord(
        task_id=task_id,
        run_id=run_id,
        verdict=snapshot,
        counts=count_findings(snapshot),
        raw_path=raw_path,
        snapshot_path=snapshot_path,
    )


def normalize_verdict(value: object) -> dict[str, Any]:
    """Validate a Verdict Schema v1 object and return its normalized snapshot."""
    verdict = _require_object(value, "Verdict")
    _require_exact_keys(
        verdict,
        required={
            "schema_version",
            "task_id",
            "run_id",
            "verifier",
            "verdict",
            "summary",
            "findings",
            "reviewed_at",
        },
        context="Verdict",
    )

    if type(verdict["schema_version"]) is not int or verdict["schema_version"] != VERDICT_SCHEMA_VERSION:
        raise VerdictInputError(
            f"Verdict schema_version must be {VERDICT_SCHEMA_VERSION}."
        )

    task_id = _normalize_task_id(verdict["task_id"])
    run_id = validate_run_id(verdict["run_id"])
    verifier = _normalize_verifier(verdict["verifier"])
    verdict_value = verdict["verdict"]
    if not isinstance(verdict_value, str) or verdict_value not in VERDICTS:
        allowed = ", ".join(sorted(VERDICTS))
        raise VerdictInputError(f"Verdict verdict must be one of: {allowed}.")
    summary = _require_nonempty_string(verdict["summary"], "Verdict summary")

    findings_value = verdict["findings"]
    if not isinstance(findings_value, list):
        raise VerdictInputError("Verdict findings must be an array.")
    findings = [
        _normalize_finding(finding, index)
        for index, finding in enumerate(findings_value)
    ]
    reviewed_at = _normalize_timestamp(verdict["reviewed_at"])

    return {
        "schema_version": VERDICT_SCHEMA_VERSION,
        "task_id": task_id,
        "run_id": run_id,
        "verifier": verifier,
        "verdict": verdict_value,
        "summary": summary,
        "findings": findings,
        "reviewed_at": reviewed_at,
    }


def count_findings(verdict: Mapping[str, Any]) -> dict[str, int]:
    """Return the blocker, warning, and note totals for a normalized verdict."""
    findings = verdict.get("findings")
    if not isinstance(findings, list):
        raise VerdictEvidenceError("Normalized verdict findings must be an array.")
    counts = {"blocker": 0, "warning": 0, "note": 0}
    for finding in findings:
        if not isinstance(finding, Mapping):
            raise VerdictEvidenceError("Normalized verdict contains an invalid finding.")
        severity = finding.get("severity")
        if severity not in counts:
            raise VerdictEvidenceError("Normalized verdict contains an unknown severity.")
        counts[severity] += 1
    return counts


def validate_run_id(run_id: object) -> str:
    """Validate a path-safe verification run identifier."""
    if not isinstance(run_id, str) or not run_id:
        raise VerdictInputError("Run id must be a non-empty string.")
    if run_id[0] not in RUN_ID_CHARACTERS - {"_", "-"}:
        raise VerdictInputError(
            "Run id must begin with an alphanumeric character and contain only "
            "letters, numbers, underscores, or hyphens."
        )
    if any(character not in RUN_ID_CHARACTERS for character in run_id):
        raise VerdictInputError(
            "Run id must contain only letters, numbers, underscores, or hyphens."
        )
    return run_id


def _evidence_path(repository: Path, task_id: str, run_id: str) -> Path:
    return repository / ".harness" / "evidence" / task_id / run_id


def _validate_saved_run_identity(
    evidence_path: Path,
    task_id: str,
    run_id: str,
) -> None:
    task = _read_evidence_json_object(evidence_path / "task.json")
    verification = _read_evidence_json_object(evidence_path / "verification.json")
    if task.get("id") != task_id:
        raise VerdictInputError(
            "Saved evidence task snapshot does not match the requested Task id."
        )
    if verification.get("task_id") != task_id or verification.get("run_id") != run_id:
        raise VerdictInputError(
            "Saved verification evidence does not match the requested Task/run identity."
        )


def _read_source_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise VerdictInputError(f"Could not read verdict file: {path}.") from error


def _read_evidence_bytes(path: Path) -> bytes:
    if not path.is_file():
        raise VerdictEvidenceError(f"Required verdict evidence file is missing: {path.name}.")
    try:
        return path.read_bytes()
    except OSError as error:
        raise VerdictEvidenceError(
            f"Could not read verdict evidence file: {path.name}."
        ) from error


def _read_evidence_json_object(path: Path) -> dict[str, Any]:
    raw = _read_evidence_bytes(path)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerdictEvidenceError(f"Evidence file '{path.name}' is not valid JSON.") from error
    if not isinstance(value, Mapping):
        raise VerdictEvidenceError(f"Evidence file '{path.name}' must be a JSON object.")
    return dict(value)


def _parse_verdict_bytes(
    raw: bytes,
    description: str,
    *,
    persisted: bool,
) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        error_type = VerdictEvidenceError if persisted else VerdictInputError
        raise error_type(f"{description} is not valid JSON.") from error
    try:
        return normalize_verdict(value)
    except VerdictError as error:
        if persisted:
            raise VerdictEvidenceError(f"{description} does not match Verdict Schema v1.") from error
        raise


def _assert_verdict_identity(
    verdict: Mapping[str, Any],
    task_id: str,
    run_id: str,
    *,
    persisted: bool,
) -> None:
    if verdict.get("task_id") == task_id and verdict.get("run_id") == run_id:
        return
    error_type = VerdictEvidenceError if persisted else VerdictInputError
    raise error_type("Verdict task_id and run_id must match the requested Task run.")


def _normalize_task_id(value: object) -> str:
    try:
        return validate_task_id(value)
    except TaskError as error:
        raise VerdictInputError(f"Verdict task_id is invalid: {error}") from error


def _normalize_verifier(value: object) -> dict[str, Any]:
    verifier = _require_object(value, "Verdict verifier")
    _require_exact_keys(
        verifier,
        required={"kind", "runner", "model", "fresh_context"},
        context="Verdict verifier",
    )
    if verifier["kind"] != "manual":
        raise VerdictInputError("Verdict verifier kind must be 'manual'.")
    runner = _require_nonempty_string(verifier["runner"], "Verdict verifier runner")
    model = verifier["model"]
    if model is not None:
        model = _require_nonempty_string(model, "Verdict verifier model")
    fresh_context = verifier["fresh_context"]
    if type(fresh_context) is not bool:
        raise VerdictInputError("Verdict verifier fresh_context must be a boolean.")
    return {
        "kind": "manual",
        "runner": runner,
        "model": model,
        "fresh_context": fresh_context,
    }


def _normalize_finding(value: object, index: int) -> dict[str, Any]:
    context = f"Verdict findings[{index}]"
    finding = _require_object(value, context)
    _require_exact_keys(
        finding,
        required={"severity", "code", "title", "detail"},
        optional={"path", "line"},
        context=context,
    )
    severity = finding["severity"]
    if not isinstance(severity, str) or severity not in SEVERITIES:
        allowed = ", ".join(sorted(SEVERITIES))
        raise VerdictInputError(f"{context} severity must be one of: {allowed}.")
    normalized: dict[str, Any] = {
        "severity": severity,
        "code": _require_nonempty_string(finding["code"], f"{context} code"),
        "title": _require_nonempty_string(finding["title"], f"{context} title"),
        "detail": _require_nonempty_string(finding["detail"], f"{context} detail"),
    }
    if "path" in finding:
        normalized["path"] = _require_nonempty_string(finding["path"], f"{context} path")
    if "line" in finding:
        line = finding["line"]
        if type(line) is not int or line <= 0:
            raise VerdictInputError(f"{context} line must be a positive integer.")
        normalized["line"] = line
    return normalized


def _normalize_timestamp(value: object) -> str:
    timestamp = _require_nonempty_string(value, "Verdict reviewed_at")
    if "T" not in timestamp:
        raise VerdictInputError("Verdict reviewed_at must be an ISO-8601 date-time.")
    parseable = f"{timestamp[:-1]}+00:00" if timestamp.endswith("Z") else timestamp
    try:
        parsed = datetime.fromisoformat(parseable)
    except ValueError as error:
        raise VerdictInputError("Verdict reviewed_at must be an ISO-8601 date-time.") from error
    if parsed.tzinfo is None:
        raise VerdictInputError(
            "Verdict reviewed_at must include an ISO-8601 UTC offset."
        )
    return timestamp


def _require_object(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VerdictInputError(f"{context} must be a JSON object.")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    context: str,
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    missing = required - set(value)
    unexpected = set(value) - required - optional
    if missing:
        names = ", ".join(sorted(missing))
        raise VerdictInputError(f"{context} is missing required field(s): {names}.")
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise VerdictInputError(f"{context} has unexpected field(s): {names}.")


def _require_nonempty_string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VerdictInputError(f"{context} must be a non-empty string.")
    return value


def _atomic_write_json(path: Path, value: object) -> None:
    contents = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    _atomic_write_bytes(path, f"{contents}\n".encode("utf-8"))


def _atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            output.write(value)
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
