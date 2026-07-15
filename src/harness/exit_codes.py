"""Stable Outcome Harness command exit codes.

These values are part of the public command-line contract from Phase 1c
onward.  New commands may use a subset, but existing meanings must not be
reassigned.
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Documented process exit codes for Outcome Harness."""

    SUCCESS = 0
    INVALID_INPUT_OR_SCHEMA = 2
    GIT_OR_REPOSITORY_ERROR = 3
    SCOPE_VIOLATION = 4
    REQUIRED_CHECK_FAILURE = 5
    TIMEOUT = 6
    REQUIRED_VERIFIER_EVIDENCE_MISSING = 7
    EVIDENCE_MISSING_OR_CORRUPT = 8
