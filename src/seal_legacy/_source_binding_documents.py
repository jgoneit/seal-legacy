"""Persisted Source Binding document validation for Evidence v2.

This module reads and cross-checks the historical S0/S1 Snapshot artifacts.
It deliberately does not inspect Git or the current Working Tree; complete-time
S2 collection belongs to :mod:`seal_legacy._source_binding`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ._run_artifact_io import RunArtifactReadError, read_run_artifact_bytes
from .source_snapshot import (
    SOURCE_SNAPSHOT_SCHEMA_VERSION,
    SourceSnapshot,
    SourceSnapshotError,
    _source_snapshot_from_document,
)


SOURCE_BOUND_EVIDENCE_VERSION = 2

SOURCE_BEFORE_CHECKS_FILENAME = "source-before-checks.json"
SOURCE_AFTER_CHECKS_FILENAME = "source-after-checks.json"
SOURCE_BINDING_EVIDENCE_FILES = (
    SOURCE_BEFORE_CHECKS_FILENAME,
    SOURCE_AFTER_CHECKS_FILENAME,
)

SOURCE_SNAPSHOT_SCHEMA_VERSION_FIELD = "source_snapshot_schema_version"
SOURCE_BEFORE_CHECKS_SHA256_FIELD = "source_before_checks_sha256"
SOURCE_AFTER_CHECKS_SHA256_FIELD = "source_after_checks_sha256"
SOURCE_STABLE_DURING_CHECKS_FIELD = "source_stable_during_checks"
SOURCE_BINDING_VERIFICATION_FIELDS = frozenset(
    {
        SOURCE_SNAPSHOT_SCHEMA_VERSION_FIELD,
        SOURCE_BEFORE_CHECKS_SHA256_FIELD,
        SOURCE_AFTER_CHECKS_SHA256_FIELD,
        SOURCE_STABLE_DURING_CHECKS_FIELD,
    }
)

_FULL_OBJECT_ID_LENGTHS = frozenset({40, 64})
_LOWER_HEX = frozenset("0123456789abcdef")


class SourceBindingDocumentError(ValueError):
    """Base error for persisted Source Binding document validation."""


class SourceBindingArtifactError(SourceBindingDocumentError):
    """Raised when a required S0/S1 artifact cannot be read or parsed."""


class SourceBindingConsistencyError(SourceBindingDocumentError):
    """Raised when stored Source Binding facts disagree with each other."""


@dataclass(frozen=True)
class StoredSourceBinding:
    """One validated, immutable historical S0/S1 Source Binding."""

    source_before_checks: SourceSnapshot
    source_after_checks: SourceSnapshot
    source_stable_during_checks: bool


def load_and_validate_stored_source_binding(
    evidence_path: Path,
    *,
    task: Mapping[str, Any],
    changed_files: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> StoredSourceBinding:
    """Read and cross-check the persisted Source Binding for one v2 Run."""
    source_before_checks = _read_source_snapshot(
        evidence_path,
        SOURCE_BEFORE_CHECKS_FILENAME,
    )
    source_after_checks = _read_source_snapshot(
        evidence_path,
        SOURCE_AFTER_CHECKS_FILENAME,
    )

    recorded_snapshot_version = verification.get(
        SOURCE_SNAPSHOT_SCHEMA_VERSION_FIELD
    )
    if (
        type(recorded_snapshot_version) is not int
        or recorded_snapshot_version != SOURCE_SNAPSHOT_SCHEMA_VERSION
    ):
        raise SourceBindingConsistencyError(
            "verification.json source_snapshot_schema_version does not match "
            "the supported Source Snapshot schema."
        )

    baseline = _validated_common_baseline(
        task,
        changed_files,
        verification,
        source_before_checks,
        source_after_checks,
    )
    if source_before_checks.baseline != baseline:
        raise SourceBindingConsistencyError(
            f"{SOURCE_BEFORE_CHECKS_FILENAME} baseline does not match "
            "the saved Task baseline."
        )
    if source_after_checks.baseline != baseline:
        raise SourceBindingConsistencyError(
            f"{SOURCE_AFTER_CHECKS_FILENAME} baseline does not match "
            "the saved Task baseline."
        )

    _validate_recorded_digest(
        verification,
        SOURCE_BEFORE_CHECKS_SHA256_FIELD,
        source_before_checks.snapshot_sha256,
        SOURCE_BEFORE_CHECKS_FILENAME,
    )
    _validate_recorded_digest(
        verification,
        SOURCE_AFTER_CHECKS_SHA256_FIELD,
        source_after_checks.snapshot_sha256,
        SOURCE_AFTER_CHECKS_FILENAME,
    )

    recorded_stability = verification.get(SOURCE_STABLE_DURING_CHECKS_FIELD)
    if type(recorded_stability) is not bool:
        raise SourceBindingConsistencyError(
            "verification.json source_stable_during_checks must be a boolean."
        )
    computed_stability = source_before_checks == source_after_checks
    if recorded_stability != computed_stability:
        raise SourceBindingConsistencyError(
            "verification.json source_stable_during_checks does not match "
            "the persisted pre-check and post-check Source Snapshots."
        )

    return StoredSourceBinding(
        source_before_checks=source_before_checks,
        source_after_checks=source_after_checks,
        source_stable_during_checks=computed_stability,
    )


def _read_source_snapshot(
    evidence_path: Path,
    filename: str,
) -> SourceSnapshot:
    relative_path = PurePosixPath(filename)
    try:
        raw_document = read_run_artifact_bytes(evidence_path, relative_path)
    except RunArtifactReadError as error:
        if error.reason == "missing":
            detail = "is missing"
        elif error.reason == "unsafe":
            detail = "is unsafe or missing"
        else:
            detail = "could not be read"
        raise SourceBindingArtifactError(
            f"Required Source Binding artifact '{filename}' {detail}."
        ) from error

    try:
        document = json.loads(raw_document.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceBindingArtifactError(
            f"Source Binding artifact '{filename}' is not valid JSON."
        ) from error
    if not isinstance(document, Mapping):
        raise SourceBindingArtifactError(
            f"Source Binding artifact '{filename}' must be a JSON object."
        )

    try:
        return _source_snapshot_from_document(document)
    except SourceSnapshotError as error:
        raise SourceBindingArtifactError(
            f"Source Binding artifact '{filename}' is invalid: {error}"
        ) from error


def _validated_common_baseline(
    task: Mapping[str, Any],
    changed_files: Mapping[str, Any],
    verification: Mapping[str, Any],
    source_before_checks: SourceSnapshot,
    source_after_checks: SourceSnapshot,
) -> str:
    named_baselines = (
        ("saved Task", task.get("baseline")),
        ("changed-files.json", changed_files.get("baseline")),
        ("verification.json", verification.get("baseline")),
        (SOURCE_BEFORE_CHECKS_FILENAME, source_before_checks.baseline),
        (SOURCE_AFTER_CHECKS_FILENAME, source_after_checks.baseline),
    )
    for context, value in named_baselines:
        if not _is_full_object_id(value):
            raise SourceBindingConsistencyError(
                f"{context} baseline must be a full Git commit object id."
            )

    baseline = named_baselines[0][1]
    assert isinstance(baseline, str)
    if any(value != baseline for _, value in named_baselines[1:]):
        raise SourceBindingConsistencyError(
            "Source-bound Evidence baselines do not match the saved Task baseline."
        )
    return baseline


def _validate_recorded_digest(
    verification: Mapping[str, Any],
    field: str,
    computed_digest: str,
    filename: str,
) -> None:
    recorded_digest = verification.get(field)
    if not _is_sha256(recorded_digest):
        raise SourceBindingConsistencyError(
            f"verification.json {field} must be a lowercase SHA-256 digest."
        )
    if recorded_digest != computed_digest:
        raise SourceBindingConsistencyError(
            f"verification.json {field} does not match {filename}."
        )


def _is_full_object_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) in _FULL_OBJECT_ID_LENGTHS
        and all(character in _LOWER_HEX for character in value)
    )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in _LOWER_HEX for character in value)
    )
