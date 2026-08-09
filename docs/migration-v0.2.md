# Migrating verification Evidence to v0.2

This note describes the verification Evidence compatibility boundary in
Harness Core `0.2.x`.

## Verification Run contract

v0.2 Core supports source-bound verification Evidence v2 only. Every supported
Run contains:

- `verification.json` with `schema_version: 2`;
- `source-before-checks.json` for S0; and
- `source-after-checks.json` for S1.

An unsupported verification schema version is rejected as missing or corrupt
stored Evidence with exit 8. Exit 9 is reserved for a structurally valid v2 Run
whose current-source binding fails because S0 differs from S1 or S1 differs
from completion-time S2.

Task, changed-files, checks, Run Manifest, Bundle, Verdict, Completion, and
Source Snapshot Schema versions remain unchanged.

## v0.1.x Evidence

Harness does not provide an in-place migration, converter, adapter, or automatic
upgrade for v0.1.x Evidence. Use the CLI from the corresponding v0.1.x Git tag
when historical v0.1.x Evidence must be read.

To make a current-source-bound completion claim, create a new verification v2
Run with v0.2 Core.
