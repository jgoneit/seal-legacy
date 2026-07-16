"""Schema-backed validation for recorded Manual Verifier Verdicts.

This module deliberately validates only the Verdict document.  It does not
reconstruct a full evidence run, invoke a verifier, or bind a run to a later
source-tree state.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from .task import TaskError


class VerdictValidationError(TaskError):
    """Raised when a Verdict cannot satisfy the packaged canonical contract."""


@lru_cache(maxsize=1)
def _verdict_validator() -> Draft202012Validator:
    """Load, self-check, and cache the packaged Verdict Schema."""
    try:
        contents = (
            resources.files("harness")
            .joinpath("resources", "verdict.schema.json")
            .read_text(encoding="utf-8")
        )
        schema = json.loads(contents)
    except (
        FileNotFoundError,
        ModuleNotFoundError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise VerdictValidationError(
            "Packaged Verdict Schema is missing, unreadable, or invalid JSON."
        ) from error

    try:
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema, format_checker=FormatChecker())
    except (SchemaError, TypeError, ValueError) as error:
        raise VerdictValidationError("Packaged Verdict Schema is invalid.") from error


def validate_verdict(
    value: object,
    *,
    expected_task_id: str | None = None,
    expected_run_id: str | None = None,
) -> dict[str, Any]:
    """Validate one Verdict and return an independent canonical snapshot.

    JSON Schema owns the document shape, fields, enums, types, formats, and
    unknown-property policy.  Optional expected identities are context checks
    for the specific Task/run to which the Verdict is being attached.
    """
    try:
        snapshot = copy.deepcopy(value)
    except Exception as error:  # pragma: no cover - defensive for exotic input objects.
        raise VerdictValidationError("Verdict validation failed: input cannot be copied.") from error

    try:
        errors = sorted(
            _verdict_validator().iter_errors(snapshot),
            key=lambda error: (_json_path(error.absolute_path), error.message),
        )
    except VerdictValidationError:
        raise
    except Exception as error:  # pragma: no cover - jsonschema protects normal JSON inputs.
        raise VerdictValidationError("Verdict validation could not be completed.") from error

    if errors:
        error = errors[0]
        raise VerdictValidationError(
            f"Verdict validation failed at {_json_path(error.absolute_path)}: {error.message}"
        )

    if not isinstance(snapshot, dict):
        raise VerdictValidationError("Verdict validation failed at $: expected an object.")
    if expected_task_id is not None and snapshot["task_id"] != expected_task_id:
        raise VerdictValidationError(
            "Verdict validation failed at task_id: does not match the requested Task id."
        )
    if expected_run_id is not None and snapshot["run_id"] != expected_run_id:
        raise VerdictValidationError(
            "Verdict validation failed at run_id: does not match the requested run id."
        )
    return snapshot


def finding_severities() -> tuple[str, ...]:
    """Return the finding severities declared by the packaged Schema.

    This supports reporting counts without creating a second hard-coded
    severity contract in Verdict storage code.
    """
    schema = _verdict_validator().schema
    try:
        values = schema["$defs"]["finding"]["properties"]["severity"]["enum"]
    except (KeyError, TypeError) as error:  # pragma: no cover - guarded by the shipped schema.
        raise VerdictValidationError(
            "Packaged Verdict Schema does not define finding severities."
        ) from error
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise VerdictValidationError(
            "Packaged Verdict Schema does not define usable finding severities."
        )
    return tuple(values)


def _json_path(path: object) -> str:
    """Format a jsonschema path using stable, readable JSON-path notation."""
    result = ""
    for segment in path:  # type: ignore[union-attr]
        if isinstance(segment, int):
            result += f"[{segment}]"
        elif isinstance(segment, str) and segment.isidentifier():
            result += f".{segment}" if result else segment
        else:
            result += f"[{segment!r}]"
    return result or "$"
