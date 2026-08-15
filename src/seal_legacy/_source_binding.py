"""Complete-time binding of validated Evidence v2 to current product source."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from .source_snapshot import (
    SourceSnapshot,
    SourceSnapshotError,
    collect_source_snapshot,
)


class SourceBindingError(RuntimeError):
    """Base error for complete-time current-source binding."""


class SourceBindingNotSatisfiedError(SourceBindingError):
    """Raised when a Run cannot make a current-source-bound claim."""


class SourceBindingCollectionError(SourceBindingError):
    """Raised when the current product source cannot be collected safely."""


class SourceBindingMismatchError(SourceBindingNotSatisfiedError):
    """Raised when valid historical and current Source Snapshots disagree."""


class _ValidatedRunForSourceBinding(Protocol):
    """The narrow immutable Run view required by complete-time binding."""

    repository: Path
    task: Mapping[str, object]
    source_before_checks: SourceSnapshot
    source_after_checks: SourceSnapshot
    source_stable_during_checks: bool


def evaluate_completion_source_binding(
    validated_run: _ValidatedRunForSourceBinding,
) -> SourceSnapshot:
    """Collect S2 and require a stable S0 == S1 == S2 source identity.

    Stored Evidence validation must run before this function.  This boundary
    intentionally collects only S2; it neither reads persisted artifacts nor
    reruns checks.
    """
    source_before_checks = validated_run.source_before_checks
    source_after_checks = validated_run.source_after_checks

    try:
        current_source = collect_source_snapshot(
            validated_run.task,
            cwd=validated_run.repository,
        )
    except SourceSnapshotError as error:
        raise SourceBindingCollectionError(
            f"Could not collect current product source: {error}"
        ) from error

    if (
        not validated_run.source_stable_during_checks
        or source_before_checks != source_after_checks
    ):
        raise SourceBindingMismatchError(
            "Source binding is not satisfied because product source changed "
            "while verification checks were running."
        )
    if source_after_checks != current_source:
        raise SourceBindingMismatchError(
            "Source binding is not satisfied because current product source "
            "does not match the post-check Source Snapshot."
        )
    return current_source
