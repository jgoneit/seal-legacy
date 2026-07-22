# Harness architecture

Language: English | [한국어](architecture.ko.md)

## Responsibility boundaries

Harness does not control the coding Agent's work process, tool calls, reasoning, or runtime state. Its responsibility is to preserve stored changes, check results, and Manual Verdicts for a specific Task as readable Evidence, and to evaluate saved Run integrity separately from completion policy.

This boundary separates two things:

- changes made by the implementer and mechanical results collected by Harness
- a Manual Verdict provided by a person and the persistence, revalidation, and completion gate performed by Harness

Harness does not generate Manual Verdicts or guarantee verifier independence. The only verifier path currently provided is a manual path that records and shows JSON submitted by the user.

## Responsibilities by module

| Module | Responsibility |
| --- | --- |
| harness.cli | Connect CLI arguments to command-specific functions and return stable exit codes |
| harness.task | Read the Task Spec and check catalog, then save the Task snapshot and baseline |
| harness.gitdiff | Collect product changes and scope information between the baseline and current working tree |
| harness.checks | Run checks as argv arrays and record stdout and stderr inside the Run |
| harness.run_manifest | Generate and compare the size and SHA-256 of raw mechanical Evidence bytes and the canonical `evidence_sha256` |
| harness.run_validator | Canonically validate identity, paths, checks, scope, and mechanical-result consistency in stored Task/Run Evidence |
| harness.evidence | Store mechanical Evidence and process the completion policy and completion record for a validated Run |
| harness.bundle | Create a portable bundle from limited Evidence in a validated Run and the packaged verifier instructions |
| harness.verdict_validator | Validate Verdict structure and format and Task/run context using the packaged Verdict Schema |
| harness.verdict | Preserve the raw Manual Verdict, store its canonical snapshot, revalidate it, and calculate finding counts |

`schemas/verdict.schema.json` and `prompts/verifier.md` at the repository root are the human-edited canonical contracts. The matching files under `src/harness/resources` are mirrors included in the package, and `scripts/sync_contracts.py` checks that they are synchronized byte for byte.

## Flow from Task to completion

    Task Spec
       │ task create
       ▼
    Task snapshot + baseline
       │ verify
       ▼
    Evidence Run
       ├── mechanical result
       ├── verifier bundle
       └── Manual Verdict record
                │
                ▼
             complete

`task create` saves a snapshot of the Task Spec and records the current Git HEAD as its baseline. By default, `verify` saves scope-related changes from that baseline through the current working tree in the Run directory. The optional `--base-ref` was introduced in v0.1.0 and remains available in v0.1.1; it can override the baseline for that Run and is a published known limitation. `bundle` exports only the limited payload needed for review without rerunning the saved Run.

`complete`, `bundle`, and `verifier record/show` first read the specified Task/run through `validate_run()`. This validator does not recalculate checks or the Git diff, and it does not select the latest Run implicitly.

## Run integrity and completion policy

`validate_run()` determines only whether a saved Run can be read without internal contradictions. A required check failure, timeout, Scope violation, or `mechanical_result="fail"` may be a failed work result, but it is not corrupted Evidence. Such a Run is therefore still returned as a `ValidatedRun` and can be exported as a bundle or have a Manual Verdict recorded.

Completion policy is a separate responsibility applied afterward. For a Run already determined to be valid, `complete` applies Scope pass, required check pass, absence of timeouts, and required Verdict and blocker conditions. Completion refusal is distinguished from Run integrity errors through stable exit codes.

The validator reads only the stored `.harness/tasks/<TASK_ID>.json` and artifacts inside the Run. It does not collect the current source tree, regenerate the Git diff, or rerun checks, and it does not control the Agent's tool usage, approvals, worktrees, or repair flow.

## Mechanical result and Manual Verdict

The mechanical result is calculated from the scope pass and required check results. A Manual Verdict is a separate input from the mechanical result and does not overwrite or correct it.

Completion considers all of the following:

- consistency among the stored Task/run identity and Evidence
- consistency among scope, required check results, and the mechanical result
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
    ├── verification.json
    ├── run-manifest.json
    ├── verdict.raw.json
    ├── verdict.json
    └── completion.json

The first five mechanical Evidence files and the check logs are created by `verify`. `run-manifest.json` collects raw-byte records for those mechanical files and is saved in the final step of verification. Verdict files are created only after `verifier record` succeeds, and `completion.json` is created only after `complete` passes every gate. The manifest does not include itself, Verdict, or Completion.

## Current integrity model

The current model uses `validate_run()` as the single integrity boundary for stored mechanical Evidence.

- It compares the requested Task/run identity, saved Task snapshot, Run `task.json`, and the identity in `verification.json`.
- It checks required Evidence files, JSON readability, listed Evidence paths, log existence, and symlink escapes outside the Run directory.
- It checks the Task check definitions against recorded check results and verifies the relationships among `passed`, `timed_out`, and `exit_code`.
- It uses stored data to recalculate and compare the changed-files baseline, product changes, scope violations, `scope_pass`, `required_checks_pass`, and `mechanical_result`.
- It compares the expected mechanical file list with the sorted records in `run-manifest.json`, then recalculates each raw-byte size and SHA-256 and the timestamp-independent canonical `evidence_sha256`.
- It revalidates the raw Verdict and normalized snapshot against the separate Verdict contract and verifies that they match.
- Completion records the validated Run's `evidence_sha256`; a bundle records it as `source_evidence_sha256` and creates a separate `bundle_sha256` for the portable payload.

This is not cryptographic provenance or immutable storage. The manifest detects modification, omission, or replacement of mechanical files after verification, but it cannot prevent the same local user from editing both the Evidence and a recalculated manifest. `evidence_sha256` and the bundle hash are neither completion authority nor remote attestation.

## Known limitations and the next design boundary

The current implementation does not bind the source at verification time to the source at a later time. The manifest verifies only the local consistency of the mechanical Evidence saved at that time; semantic binding between the diff and changed-files, pre/post-check snapshot comparison, and snapshot fingerprints do not exist yet. Therefore, neither `validate_run()` nor `complete` should be interpreted as revalidating the "current source."

`verify --base-ref` can record a separate Git ref as the baseline for a Run instead of the saved Task baseline. This option remains an explicit override in v0.1.1 and does not provide source binding or Task baseline immutability.

Check output may contain sensitive values. Harness attempts to make absolute paths portable, but it does not provide complete secret redaction.

Future snapshot binding must be handled as a separate extension to Run integrity. It is a different responsibility from the current Verdict structure validation and is not implicitly included in the current flow documented here.

## Why external adapters are separated from core

Core handles only local files, Git, argv-based checks, and deterministic Schema validation. External model APIs, vendor verifier CLIs, network retries, credential handling, and cost and latency policies are adapter responsibilities outside this boundary.

This separation keeps the core Evidence contract independent of any particular vendor response format or network state. If an external adapter is needed, its versioned input/output contract, failure modes, and provenance must be designed separately before it is connected to core.
