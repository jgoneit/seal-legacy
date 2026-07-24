# Harness architecture

Language: English | [한국어](architecture.ko.md)

This document describes unreleased current main `0.2.0.dev0`. v0.1.1 remains
the latest published release and retains its historical non-source-bound
completion behavior.

## Responsibility boundaries

Harness does not control the coding Agent's work process, tool calls, reasoning,
or runtime state. Its responsibility is to record Task scope, check results,
verification-time source identity, and optional user-provided review results,
then evaluate whether the current result supports a completion claim. Saved Run
integrity remains separate from completion policy.

This boundary separates two things:

- changes made by the implementer and mechanical results collected by Harness
- a Manual Verdict provided by a person and the persistence, revalidation, and completion gate performed by Harness

Harness does not generate Manual Verdicts or guarantee verifier independence. The only verifier path currently provided is a manual path that records and shows JSON submitted by the user.

## Responsibilities by module

| Module | Responsibility |
| --- | --- |
| harness.cli | Connect CLI arguments to command-specific functions and return stable exit codes |
| harness.task | Read the Task Spec and check catalog, then save the Task snapshot and baseline |
| harness._path_policy (internal) | Share component-boundary, Harness-metadata, and canonical Git-byte ordering policy without normalizing producer and validator inputs the same way |
| harness.gitdiff | Collect product changes and scope information between the baseline and current working tree |
| harness.source_snapshot | Collect the sole live canonical product-source Snapshot and parse and validate persisted Snapshot documents |
| harness.checks | Run checks as argv arrays and record stdout and stderr inside the Run |
| harness._run_artifact_io (internal) | Validate relative Run-artifact paths, read confined raw bytes, and provide the existing atomic Run-artifact writer without interpreting document meaning |
| harness.run_manifest | Generate and compare the size and SHA-256 of raw mechanical Evidence bytes and the canonical `evidence_sha256` |
| harness._run_documents (internal) | Validate persisted document shapes and cross-document check, scope, source-stability, and mechanical-result consistency |
| harness._source_binding_documents (internal) | Confine and parse persisted S0/S1 Snapshot files and cross-check their Task baseline, digests, and stability as one frozen `StoredSourceBinding` |
| harness.run_validator | Remain the sole public stored-Run integrity facade, locate the Task/Run, coordinate internal validators, and assemble immutable `ValidatedRun` values |
| harness.evidence | Collect S0/S1 around check execution and create versioned mechanical Evidence while preserving the established public verification and completion imports |
| harness._source_binding (internal) | Apply only the complete-time boundary: distinguish legacy, current collection, and historical/current mismatch failures and collect S2 through the canonical live API |
| harness._completion (internal) | Consume `ValidatedRun` and persisted Verdict evidence, apply completion policy, and atomically store `completion.json` |
| harness.bundle | Create a portable bundle from limited Evidence in a validated Run and the packaged verifier instructions |
| harness.verdict_validator | Validate Verdict structure and format and Task/run context using the packaged Verdict Schema |
| harness.verdict | Preserve the raw Manual Verdict, store its canonical snapshot, revalidate it, and calculate finding counts |

The underscore-prefixed modules are private implementation boundaries, not new
public APIs. Existing callers continue to use
`harness.run_validator.validate_run()` for stored Run integrity and the
established names under `harness.evidence` for verification and completion.
Bundle, Verdict, and completion code do not call the private document validator
as an alternative authority.

`harness._run_documents` intentionally remains one persisted-document trust
transaction even though it is a large module. Task, changed-files, check,
verification, and log documents must be loaded and cross-checked together
before their derived scope and mechanical-result values are trustworthy.
Splitting those checks now would require intermediate transfer objects or
independently callable partial validators, spreading ownership of the same
integrity invariants and creating alternate internal validation paths. A
further extraction is justified only when one responsibility has independent
inputs, outputs, and characterization coverage while remaining composed
exclusively by the public `validate_run()` facade; file size alone is not that
boundary.

`schemas/verdict.schema.json` and `prompts/verifier.md` at the repository root
are the human-edited canonical contracts. The matching files under
`src/harness/resources` are mirrors included in the package, and
`scripts/sync_contracts.py` checks that they are synchronized byte for byte.
`schemas/verification.schema.json` defines exact version 1 and version 2
persisted verification records but is not a second live Snapshot API.

## Flow from Task to completion

    Task Spec
       │ task create
       ▼
    Task snapshot + baseline
       │ verify: S0 → checks → S1
       ▼
    Evidence Run v2
       ├── source-before-checks.json (S0)
       ├── source-after-checks.json (S1)
       ├── mechanical result
       │
       ├───────────────────────────────┐
       │ basic flow                    │ reviewed flow
       ▼                               ▼
    complete: S2                 verifier bundle
       │                               │
       │                         human/fresh-context review
       │                               │
       │                         Manual Verdict record
       └───────────────┬───────────────┘
                       ▼
             source gates → policy gates

`task create` saves a snapshot of the Task Spec and records the current Git HEAD
as its full baseline commit. Current-main `verify` uses only that saved baseline;
the Run-level `--base-ref` override and its Python API have been removed.
Task-baseline revision and CI pull-request base/head selection are not implicit
fallbacks. In the basic flow, `complete` consumes the saved Run directly and an
optional-verifier Task needs no Verdict. The reviewed flow explicitly exports a
Bundle, obtains a human or fresh-context Verdict, records that user-provided
JSON, and then calls `complete`. `bundle` does not rerun the saved Run or collect
S2.

`complete`, `bundle`, and `verifier record/show` first read the specified Task/run through `validate_run()`. This validator does not recalculate checks or the Git diff, and it does not select the latest Run implicitly.

## Run integrity and completion policy

`validate_run()` determines only whether a saved Run can be read without
internal contradictions. A required-check failure, timeout, Scope violation,
S0/S1 source instability, or `mechanical_result="fail"` may be a failed work
result, but it is not corrupted Evidence. Such a Run is therefore still
returned as a `ValidatedRun` and can be exported as a bundle or have a Manual
Verdict recorded.

Completion source binding and policy are separate responsibilities applied
afterward. For a v2 stored Run already determined to be valid and a recorded
Verdict whose integrity is valid, `complete` collects current product source as
S2. A source-bound v2 Run must have S0 = S1 = S2 before `complete` applies Scope
pass, required-check pass, absence of timeouts, and required Verdict and blocker
conditions. A v1 completion path skips S2 and fails closed with exit 9.
Completion refusal is distinguished from Run integrity and Git collection
errors through stable exit codes.

The validator reads only the stored `.harness/tasks/<TASK_ID>.json` and
artifacts inside the Run. It does not collect the current source tree,
regenerate the Git diff, or rerun checks. The separate complete-time boundary
is the only consumer that collects S2. Neither boundary controls the Agent's
tool usage, approvals, worktrees, or repair flow.

## Mechanical result and Manual Verdict

For verification v2, the mechanical result is calculated from scope pass,
required-check pass, and S0/S1 source stability. A Manual Verdict is a separate
input from the mechanical result and does not overwrite or correct it.

Completion considers all of the following:

- consistency among the stored Task/run identity and Evidence
- consistency among scope, required check results, source stability, and the mechanical result
- a source-bound v2 Run whose S0, S1, and current S2 are equal
- when a verifier is required, a valid pass Verdict with zero blockers
- even when a verifier is optional, any recorded fail, unable, or blocker Verdict is not ignored

Warning and note findings are recorded as counts in the completion record, but do not block completion by themselves.

## Evidence directory

    .harness/evidence/<TASK_ID>/<RUN_ID>/
    ├── task.json
    ├── changed-files.json
    ├── diff.patch
    ├── checks.json
    ├── checks/
    │   ├── <check>.stdout
    │   └── <check>.stderr
    ├── source-before-checks.json
    ├── source-after-checks.json
    ├── verification.json
    ├── run-manifest.json
    ├── verdict.raw.json
    ├── verdict.json
    └── completion.json

The base mechanical Evidence files, both Snapshot documents, and check logs are
created by `verify`. `run-manifest.json` collects raw-byte records for those
mechanical files and is saved in the final step of verification. Verdict files
are created only after `verifier record` succeeds, and `completion.json` is
created only after `complete` passes every gate. The manifest does not include
itself, Verdict, Completion, or the ephemeral S2.

S0 collection happens before checks and before a Run directory is created. If
S1 collection or later persistence fails, no valid manifest or successful
stdout result is produced; an incomplete UUID directory and already written
logs may remain for diagnosis.

## Current integrity model

The current model uses `validate_run()` as the single integrity boundary for stored mechanical Evidence.

- It compares the requested Task/run identity, saved Task snapshot, Run `task.json`, and the identity in `verification.json`.
- It checks required Evidence files, JSON readability, listed Evidence paths, log existence, and symlink escapes outside the Run directory.
- It checks the Task check definitions against recorded check results and verifies the relationships among `passed`, `timed_out`, and `exit_code`.
- It uses stored data to recalculate and compare the changed-files baseline, product changes, scope violations, `scope_pass`, `required_checks_pass`, and `mechanical_result`.
- For verification v2, it parses S0 and S1, requires a common full Task baseline, compares their digests with the verification record, and recalculates `source_stable_during_checks` and the source-aware mechanical result.
- It compares the expected mechanical file list with the sorted records in `run-manifest.json`, then recalculates each raw-byte size and SHA-256 and the timestamp-independent canonical `evidence_sha256`.

After `validate_run()` returns, Verdict consumers separately revalidate the raw
Verdict and normalized snapshot against the Verdict contract and require them
to match. Completion records the validated Run's `evidence_sha256`; a bundle
records it as `source_evidence_sha256` and creates a separate `bundle_sha256`
for the portable payload.

This is not cryptographic provenance or immutable storage. The manifest detects modification, omission, or replacement of mechanical files after verification, but it cannot prevent the same local user from editing both the Evidence and a recalculated manifest. `evidence_sha256` and the bundle hash are neither completion authority nor remote attestation.

## Source Snapshot and binding boundary

`harness.source_snapshot.collect_source_snapshot()` remains the sole live
collection API. It calculates a deterministic read-only identity for product
source relative to the saved Task baseline, collapses committed, staged, and
unstaged transitions into the final Working Tree result, includes non-ignored
untracked product files, excludes canonical Harness metadata, and does not
limit identity to Task Scope. [ADR 0004](adr/0004-canonical-source-snapshot.md)
defines its entry, digest, symlink, special-file, and bounded-observation
semantics.

R1b invokes that unchanged collector in three distinct positions:

- S0: immediately before checks
- S1: immediately after every check has finished
- S2: during `complete`, after persisted Evidence and recorded Verdict integrity
  validation

New Runs use `verification.json` schema version 2 and store S0 and S1 as Source
Snapshot schema-version-1 documents covered by the raw-byte manifest. All other
existing document schema versions remain 1. `validate_run()` dispatches
verification v1/v2 and returns stored values; it never collects S2. Valid v1
Runs, including historical Runs created with the former baseline override,
remain reviewable and bundleable but fail current-source-bound completion with
exit 9 instead of being upgraded. Version 2 instead requires the Task,
changed-files, verification, S0, and S1 baselines to be the same full commit
SHA.

The complete-time binding rejects S0/S1 instability and S1/S2 mismatch with
exit 9. Current repository or Snapshot collection failure is exit 3; missing,
malformed, tampered, or contradictory stored Snapshot Evidence is exit 8. Only
after binding succeeds does the existing order apply: verifier 7, scope 4,
required timeout 6, and required-check failure 5. A bundle includes historical
S0/S1 but never collects S2 or becomes current-source authority.

This comparison is a bounded observation, not a filesystem transaction or lock.
The collector detects the supported races described by ADR 0004, but source can
still change after S2 is observed or after `complete` returns. The local
manifest also cannot prevent the same local user from recalculating and
rewriting all Evidence.

Bundle export replaces only known spellings of the current repository root,
the user home, and the selected Evidence directory. Structured JSON keys and
values, `diff.patch`, stdout, and stderr share that one replacement set.
Arbitrary bytes and other POSIX, Windows, UNC, URL, route, shell, application,
and configuration path text are preserved. The staging directory used for the
atomic Bundle write is not a payload field. This is not general path
anonymization, secret scanning, or DLP, and check output may still contain
sensitive values.

## Why external adapters are separated from core

Core handles only local files, Git, argv-based checks, and deterministic Schema validation. External model APIs, vendor verifier CLIs, network retries, credential handling, and cost and latency policies are adapter responsibilities outside this boundary.

This separation keeps the core Evidence contract independent of any particular vendor response format or network state. If an external adapter is needed, its versioned input/output contract, failure modes, and provenance must be designed separately before it is connected to core.
