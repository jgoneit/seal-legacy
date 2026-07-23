# ADR 0005: Bind Completion to the Verified Product Source

Language: English | [한국어](0005-verify-complete-source-binding.ko.md)

## Status

Accepted

## Context

ADR 0004 defined a canonical identity for the final product source relative to a
saved Task baseline, but R1a did not store that identity in Evidence or compare
it at completion. A Run could therefore describe checks performed against one
source state while `complete` accepted the Run after the product source had
changed. The Run-level `verify --base-ref` override also allowed a verification
baseline to differ from the baseline saved with the Task.

Source binding must preserve the existing separation between stored Run
integrity and current-source policy. Historical Runs must remain reviewable,
and bundle and Verdict operations must not become authorities for the current
Working Tree.

## Decision

- Remove `verify --base-ref` and its Python API path. Verification and Source
  Snapshots use only the full commit SHA saved as the Task baseline.
- A new verification Run uses `verification.json` schema version 2. The Task,
  changed-files, checks, manifest, bundle, Verdict, and Completion document
  schemas remain version 1; each Source Snapshot document also uses Snapshot
  schema version 1.
- Before checks, `verify` collects S0 and, immediately after all checks finish,
  collects S1 through the sole live collection API,
  `collect_source_snapshot()`. Required or optional check failure and timeout
  do not skip S1 when collection remains possible.
- The Run stores S0 as `source-before-checks.json` and S1 as
  `source-after-checks.json`. Both raw files are covered by
  `run-manifest.json`.
- `verification.json` v2 records
  `source_snapshot_schema_version`, `source_before_checks_sha256`,
  `source_after_checks_sha256`, and `source_stable_during_checks`.
  `source_stable_during_checks` is true exactly when S0 equals S1, and the
  mechanical result is recomputed from scope pass, required-check pass, and
  source stability.
- S0 collection failure occurs before checks and before a Run directory is
  created. An S1 or later persistence failure does not create a valid manifest
  or successful stdout result; an incomplete UUID directory and already
  written logs may remain for diagnosis.
- `validate_run()` remains the single public authority for persisted Run
  integrity and never reads the current Working Tree. Version-specific
  validators parse and cross-check the stored Snapshot documents, baselines,
  digests, stability flag, aggregate result, and manifest records.
- `complete` performs a separate current-source step after persisted Evidence
  and any recorded Verdict have passed integrity validation. For a v2 Run it
  collects S2 through `collect_source_snapshot()` and requires S0 = S1 = S2
  before applying verifier, scope, timeout, and required-check policy. S2 is
  not stored.
- Completion refuses a structurally valid legacy v1 Run, S0/S1 instability, or
  an S1/S2 mismatch with exit 9. Corrupt stored Evidence returns exit 8, and a
  failure to collect the current Snapshot returns exit 3. The remaining
  precedence is verifier 7, scope 4, required timeout 6, and required-check
  failure 5.
- A v1 Run remains valid input to `validate_run()`, bundle export, and Verdict
  record/show, including historical Runs whose recorded baseline came from the
  former override. Its completion path does not collect S2. It is not upgraded
  in place and must be reverified to become eligible for source-bound
  completion.
- A bundle includes persisted S0 and S1 for a v2 Run, but does not collect S2,
  rerun checks, compare current source, or decide completion.

## Consequences

A check that creates, modifies, deletes, renames, or changes the executable mode
of product source makes S0 differ from S1 and leaves a structurally valid failed
Run when Evidence persistence succeeds. Gitignored untracked files and
canonical Harness metadata remain outside Snapshot identity.

After verification, a content, path, mode, symlink-target, or binary-byte change
that makes S2 differ from S1 prevents completion. Moving unchanged final source
among unstaged, staged, and committed states does not change the identity, and
restoring the exact S1 source makes the binding eligible again.

This is a bounded local observation, not a transactional filesystem snapshot.
It can detect the supported races defined by ADR 0004, but it does not prevent
the source from changing after S2 is observed or after `complete` returns. It is
also not a signature, remote attestation, immutable ledger, or defense against
the same local user rewriting all Evidence and its manifest.

This decision does not add Task revision, CI pull-request base/head semantics,
automatic formatter or code-generation allowances, check reruns, source
rollback, external verifier APIs, or a release.

## Rejected alternatives

- Add Source Binding fields silently to `verification.json` version 1
- Let `validate_run()` read the current Working Tree
- Let bundle or Verdict commands enforce current-source equality
- Preserve `--base-ref` as a deprecated option, hidden alias, or environment
  fallback
- Automatically allow checks to change selected product-source paths
- Persist or attest S2 as though completion were an immutable point in time
