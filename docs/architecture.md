# Harness architecture

This document describes the `0.3.0.dev0` Core development line, which retains
source-bound verification Evidence v2 only. The latest published release is
`v0.2.1`. See
[Migrating verification Evidence to v0.2](migration-v0.2.md) for historical
v0.1.x Evidence.

## Responsibility boundaries

Harness is a local outcome-verification Core, not a command-control or
credential-enforcement layer.

| Boundary | Responsibility |
| --- | --- |
| Task | Validate a Task Spec, resolve named checks, and save the Task snapshot and full Git baseline |
| Verify | Collect S0, execute saved checks, collect S1, record Git changes and logs, and write Evidence v2 |
| `validate_run()` | Validate one stored Task/run pair, its S0/S1 documents, and its raw-byte Run Manifest |
| Run Summary | Project one `ValidatedRun` into transient machine-readable state without a transition |
| Bundle | Export a limited portable view of a validated Run without rerunning it |
| Verdict | Validate and preserve a user-provided Manual Verdict for a validated Run |
| Complete | Validate the Run and Verdict, collect S2, enforce source binding, and apply completion policy |
| Adapter | Invoke the Core CLI as a subprocess and relay documented stdout, stderr, and exit codes |

`validate_run()` is the only public authority for stored Run integrity. Run
Summary, Bundle, Verdict, and completion consumers do not reconstruct or
partially validate the stored Evidence contract themselves.

## Core modules

| Module | Responsibility |
| --- | --- |
| `harness.task` | Task parsing, check-catalog resolution, snapshot storage, and baseline capture |
| `harness.checks` | Ordered argv-based check execution, timeout handling, and log capture |
| `harness.gitdiff` | Canonical baseline-relative changed-file collection |
| `harness.source_snapshot` | Canonical deterministic product-source identity |
| `harness.evidence` | S0/check/S1 orchestration and atomic Evidence v2 persistence |
| `harness._run_documents` | Persisted mechanical-document validation |
| `harness._source_binding_documents` | Persisted S0/S1 parsing and cross-document consistency |
| `harness.run_manifest` | Raw-byte manifest creation and validation |
| `harness.run_validator` | Public stored-Run integrity facade |
| `harness.bundle` | Portable validated-Run export |
| `harness.verdict` | Manual Verdict record and retrieval |
| `harness._source_binding` | Completion-time S2 collection and S0/S1/S2 comparison |
| `harness._completion` | Completion policy and completion record |
| `harness.cli` | Stable command, JSON stdout, stderr, exit-code mapping, and the private transient Run Summary projection |

`schemas/verdict.schema.json` and `prompts/verifier.md` are canonical human-facing
contracts. Their mirrors in `src/harness/resources` are packaged, and
`scripts/sync_contracts.py` checks byte-for-byte synchronization.

## Flow

```text
Task Spec
   │ harness task create
   ▼
Task snapshot + full baseline commit
   │ implementation
   ▼
harness verify: collect S0 → run checks → collect S1
   ▼
Stored Evidence v2
   ├── run show: validate once → transient stored-state JSON
   ├── optional verifier bundle export
   ├── optional user-provided Manual Verdict record/show
   └── explicit complete: validate → collect S2 → source gates → policy gates
```

The saved Evidence Run is the end of the minimum default flow. Bundle export,
Verdict operations, and completion evaluation happen only when explicitly
requested.

`run show` is a state-only branch. It requires an explicit Task ID and Run ID,
calls `validate_run()` once, and projects only the returned immutable snapshot.
It does not write an artifact, rerun checks, collect current S2, read Verdict or
completion records, evaluate completion eligibility, select a latest Run, or
recommend a transition.

`verify` uses only the baseline saved in the Task snapshot. The former
Run-level baseline override is not part of the current contract.

## Evidence v2

A supported Run contains these mechanical files:

```text
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
└── run-manifest.json
```

`verification.json` uses schema version 2. Task, changed-files, checks, Run
Manifest, Source Snapshot, Bundle, Verdict, and Completion documents retain
their existing schema versions.

The Run Manifest covers every listed mechanical file by repository-relative
path, raw-byte size, and SHA-256 digest, then identifies the aggregate with
`evidence_sha256`. Verdict and completion records are later consumer artifacts
and are not mechanical Run files.

Missing, malformed, tampered, contradictory, or unsupported stored Evidence is
exit 8. Failed checks, timeouts, Scope violations, and source instability are
validly recorded failed outcomes rather than corrupt Evidence. Accordingly,
`run show` returns exit 0 for those valid failed Runs and represents the state
in its JSON envelope; it returns no envelope for corrupt Evidence.

## Source binding and completion

`collect_source_snapshot()` is the sole live product-source collector:

- S0 is collected immediately before checks.
- S1 is collected after every check finishes.
- S2 is collected by `complete` after stored Run and Verdict integrity
  validation.

S0 and S1 are required persisted Source Snapshot schema-version-1 documents.
They share the saved full baseline commit with the Task, changed-files, and
verification documents.

Completion requires S0 = S1 = S2. S0/S1 instability or S1/S2 mismatch is exit
9. Current repository or S2 collection failure is exit 3. After source binding
succeeds, completion applies the existing policy order: verifier 7, Scope 4,
required timeout 6, and required-check failure 5.

This is a bounded observation, not a filesystem transaction or lock. Source can
change after S2 is observed or after completion returns.

## Bundle and trust boundary

A bundle contains validated Task, changed-file, check, verification, diff,
S0/S1, log, and packaged verifier-instruction payloads. It does not collect S2,
rerun checks, execute a verifier, or become current-source authority.

Bundle export replaces known spellings of the current repository root with `.`
and the user home with `<HOME>`. Other POSIX, Windows, UNC, and URL-like text and
arbitrary check-output bytes are preserved. This is not general path
anonymization or secret redaction.

The manifest detects accidental or partial local Evidence modification. It does
not provide immutable storage, cryptographic provenance, remote attestation, or
protection from a local user who rewrites both Evidence and its manifest.

External models, vendor verifier CLIs, network retries, credential handling,
and cost or latency policy remain outside Core. The public subprocess boundary
is documented in [Harness Adapter CLI Contract](adapter-contract.md).
