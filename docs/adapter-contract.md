# Seal Legacy Adapter CLI Contract

This document defines the public subprocess contract for a thin adapter. The
current Core development line is `0.3.0.dev0`; the current source Seal Legacy Plugin
development version is `0.3.0-dev.0`; and Seal Legacy Core (Python) is not yet published. An
adapter must not
import the Core Python package. It uses only the CLI and stdout JSON described
below.

The current CLI reads only the v0.3 state root. An adapter must not infer a
legacy fallback or perform state-root conversion or migration on Core's behalf.

## Public CLI

| Command | Required arguments |
| --- | --- |
| `seal-legacy --version` | None |
| `seal-legacy task create` | `--file <TASK_JSON>` |
| `seal-legacy task show` | `<TASK_ID>` |
| `seal-legacy verify` | `<TASK_ID>` |
| `seal-legacy run show` | `<TASK_ID> --run-id <RUN_ID>` |
| `seal-legacy verifier bundle` | `<TASK_ID> --run-id <RUN_ID> --output <DIR>` |
| `seal-legacy verifier record` | `<TASK_ID> --run-id <RUN_ID> --file <VERDICT_JSON>` |
| `seal-legacy verifier show` | `<TASK_ID> --run-id <RUN_ID>` |
| `seal-legacy complete` | `<TASK_ID> --run-id <RUN_ID>` |

Core does not support `verify --base-ref`, a hidden alias, or an
environment fallback. Supplying `--base-ref` is invalid argparse input and
returns exit 2. Verification always uses the full baseline commit saved in the
Task snapshot. Task baseline revision and CI-specific base/head selection are
separate, unsupported concerns.

`run show` is new in Core `0.3.0.dev0`. It requires both identities and never
selects a latest Run. It is a read-only state query, not a lifecycle
transition.

## Success stdout

Except for `--version` and `--help`, successful stdout from every command above is a single UTF-8 JSON object. Diagnostic text is not appended to stdout JSON on success. Plain-text output from `--version` and `--help` is an intentional exception.

| Command | Required success JSON fields |
| --- | --- |
| `task create` | `schema_version`, `id`, `type`, `objective`, `scope`, `checks`, `risk`, `verifier`, `baseline` |
| `task show` | `schema_version`, `id`, `type`, `objective`, `scope`, `checks`, `risk`, `verifier`, `baseline` |
| `verify` | `run_id`, `evidence_path` |
| `run show` | `schema_version`, `task_id`, `run_id`, `evidence_sha256`, `mechanical_result`, `scope_pass`, `scope_violations`, `required_checks_pass`, `source_stable_during_checks`, `checks` |
| `verifier bundle` | `task_id`, `run_id`, `bundle_path`, `manifest_path`, `total_size_bytes`, `bundle_sha256` |
| `verifier record` | `task_id`, `run_id`, `raw_verdict_path`, `verdict_path` |
| `verifier show` | `schema_version`, `task_id`, `run_id`, `verifier`, `verdict`, `summary`, `findings`, `reviewed_at` |
| `complete` | `task_id`, `run_id`, `completion_path` |

Path fields may contain local absolute paths in the repository where the command ran. An adapter must treat them as opaque local paths and must not reuse them on another host or in another repository.

### Validated Run Summary v1

The public envelope identifier is `validated-run-summary/v1`.

Core `0.3.0.dev0` defines this exact transient success envelope for
`seal-legacy run show <TASK_ID> --run-id <RUN_ID>`:

```json
{
  "checks": [
    {
      "exit_code": 0,
      "name": "unit-test",
      "passed": true,
      "required": true,
      "timed_out": false
    }
  ],
  "evidence_sha256": "<SHA256>",
  "mechanical_result": "pass",
  "required_checks_pass": true,
  "run_id": "<RUN_ID>",
  "schema_version": 1,
  "scope_pass": true,
  "scope_violations": [],
  "source_stable_during_checks": true,
  "task_id": "<TASK_ID>"
}
```

Every check object has exactly `name`, `required`, `passed`, `timed_out`, and
`exit_code`. The `checks` array contains every validated saved check in saved
Task order. `exit_code` is an integer when the process produced one and `null`
when the check process could not be started. Every Scope-violation object has
exactly `source`, `status`, `path`, and `previous_path`; `previous_path` is
`null` when there is no prior path. `scope_violations` retains the validated
recorded order rather than being re-sorted or recomputed. JSON object ordering
is not semantic. `schema_version` versions only this stdout envelope. It does
not change Evidence v2, add a persisted artifact, or define a downloadable
schema file.

The fields expose the requested identity, the validated Run Manifest digest,
and the stored mechanical state needed by a machine consumer. The envelope
intentionally excludes local Evidence paths, Task objective and baseline,
check argv and log contents, timestamps, Verdict and completion state, current
source or S2, completion eligibility, next actions, and retry or repair advice.

Core constructs the envelope only after one successful canonical
`validate_run(task_id, run_id)` call. It does not read
`verification.json` through a second interpretation path. A valid Run whose
required check failed or timed out, whose Scope failed, or whose source changed
during checks still returns exit 0 with those states represented in the JSON.
Missing, malformed, contradictory, unsupported, or unsafe Evidence returns exit
8 and no summary.

## stderr and exit codes

A successful result returns exit code `0` together with stdout JSON. A handled error writes `error: <message>` to stderr and does not mix success JSON into stdout. Input rejected by argparse—including forms that omit a required command or subcommand, such as `seal-legacy`, `seal-legacy task`, or `seal-legacy verifier`—must write usage text to stderr and return exit `2`. In this case, stdout contains no JSON.

An adapter must not assume that a failed command returns partial success JSON. In particular, if `verify` fails partway through, an evidence directory may remain, but the adapter must treat the nonzero exit as failure and must not consume stdout JSON as a result.

| Exit code | Meaning |
| ---: | --- |
| 0 | success |
| 2 | invalid input or schema |
| 3 | Git or repository error |
| 4 | scope violation at completion |
| 5 | required check failure at completion |
| 6 | required check timeout at completion |
| 7 | verifier gate not satisfied |
| 8 | evidence missing or corrupt |
| 9 | source binding not satisfied |

The existing meanings of these numbers are a stable contract. See [Exit codes](exit-codes.md) for the detailed completion decision order.

For `run show`, exit 0 means that stored Run integrity was validated and the
summary was serialized; it does not mean `mechanical_result` is `pass` or that
completion is allowed. Invalid arguments or Task/Run identity return exit 2,
repository errors return exit 3, and missing, corrupt, unsupported, or unsafe
Evidence returns exit 8. This state query does not use completion-policy exits
4–7 or 9. On success stderr is empty. On a handled error stdout is empty and
stderr is exactly the normal `error: <message>` diagnostic stream; argparse
usage errors retain argparse's usage/error format on stderr.

## Public read-only artifacts

An adapter's default boundary is the CLI and JSON. In Core `0.3.0.dev0`, an
adapter that needs mechanical Run state uses `run show` rather than interpreting
`verification.json`. It may use the following unchanged Evidence v2 read-only
artifact surface only when it needs to display or archive Evidence. An adapter
must not create or modify these files.

| Location | Documented purpose and fields |
| --- | --- |
| `.seal/tasks/<TASK_ID>.json` | Task snapshot; the same Task JSON fields as `task create`/`task show` |
| `<evidence_path>/verification.json` | Source-bound Run identity and stored mechanical outcome using verification schema version 2; a direct read is diagnostic artifact access, not stored-Run validation |
| `<evidence_path>/source-before-checks.json` | Required pre-check S0 product-source Snapshot using Source Snapshot schema version 1 |
| `<evidence_path>/source-after-checks.json` | Required post-check S1 product-source Snapshot using Source Snapshot schema version 1 |
| `<evidence_path>/run-manifest.json` | mechanical file records and local consistency identifier; `task_id`, `run_id`, `files`, `evidence_sha256` |
| `<evidence_path>/verdict.raw.json`, `verdict.json` | recorded original Manual Verdict and canonical snapshot |
| `<evidence_path>/completion.json` | Task/Run identity for successful completion and the consumed `evidence_sha256` |

Current Core supports verification schema version 2 only. Unsupported stored
verification versions are rejected with exit 8. The Task, changed-files,
checks, Run Manifest, Bundle, Verdict, Completion, and Source Snapshot document
schemas retain their existing versions.

A bundle includes S0 and S1 but remains historical: bundle creation does not
collect current S2, compare current source, rerun checks, or decide completion.

`changed-files.json`, `checks.json`, check logs, and `diff.patch` are preserved
as Evidence in the Run record above, but fields or internal representations not
listed in this document are not part of the adapter compatibility contract.
When portable review is needed, use `verifier bundle` instead of assembling
files directly from the filesystem.

A direct artifact read is not a Core-validated Run result. An adapter may
archive or inspect a documented artifact, but its contents must not drive
lifecycle decisions or completion claims. `run show`, bundle, Verdict, and
completion operations all call the canonical stored-Run validator.

## Managed adapter lifecycle

An adapter may connect existing public commands into a managed,
conversation-scoped workflow only after a literal Seal Legacy Skill invocation or
an explicitly selected Seal Legacy Plugin paired with an executable coding
outcome. Plugin selection alone, Seal Legacy discussion, explanation, planning,
audit, review, status requests, and ordinary unselected coding requests do not
activate Core. This changes adapter UX, not Core command semantics or
authority.

The adapter leads with a compact presentation summary before detailed contract
material. A non-activating request is labeled `Mode: Analysis only`; an
activated outcome is labeled `Mode: Managed execution`. Before adoption, the
summary identifies the repository, objective, Scope, HEAD baseline, check
names, profile, working-tree state, and next action. It then separates
`Included in this confirmation`, `Not included in this confirmation`, and
`Local records` before showing the full Task JSON and catalog-derived check
preview. These labels are not persisted adapter state, Core output, or new
authority. For an activated outcome, the adapter performs version, repository,
HEAD, and check-catalog preflight before drafting the Task.

If Core is missing or unsupported, the summary states `Status: Core
unavailable`, preserves the actual preflight result, and gives installation and
request-retry guidance without installing Core or implying that a Task exists.
After `verify` exits zero, the adapter uses `Status: Evidence recorded`, not
"verification passed", and states that recording Evidence does not establish
check pass or completion eligibility. After `run show` exits zero, it separately
states that stored Run integrity was validated and the summary was serialized.
`mechanical_result=pass` is only stored mechanical state. None of those states
means completion acceptance or completion eligibility. A bundle is described
as a review handoff export, not a review result.

Before the first Core write, the adapter may display a Task draft, a
catalog-derived check preview, HEAD baseline semantics, and existing
working-tree changes, then ask for one conversational confirmation. This is a
preview, not Core normalization; only successful `task create` stdout supplies
the authoritative saved checks. Set `type` to exactly one public Task Schema
value: `bugfix`, `feature`, `refactor`, `test`, `docs`, or `config-infra`. Use
`docs` when the outcome changes documentation only. Do not invent another
label such as `implementation`, `maintenance`, or `chore`. This draft guidance
does not replace Core validation. An omitted optional `timeout_seconds` remains
omitted in the preview rather than being replaced with an adapter-invented
default. The confirmation may cover Task creation, continuation of ordinary
implementation, the first `verify` exactly once, and one exact `run show` for
the Run returned by that successful `verify`; no additional question is needed
between those two commands. When the displayed Task uses the reviewed profile,
it may also cover exactly one local bundle export to a fresh absolute directory
outside the target repository, if and only if the adopted saved Task retains
`verifier.required=true`. It does not authorize Verdict record/show, reviewer
invocation, external sharing, `complete`, retry, repair, a replacement Run,
implementation permissions, or replacement of host and client approval
prompts.

After `task create`, the adapter must compare the saved stdout Task fields with
the approved draft, the saved baseline with the displayed HEAD, and the saved
normalized check fields with the approved preview. If any differs, it
preserves the created Task but stops before implementation or verification and
requires explicit adoption of the exact saved Task or a new Task draft. It
must not overwrite the created Task or treat the earlier confirmation as
approving the difference.

The conversation-carried identity consists of the canonical repository root,
Task ID, and, when available, Run ID plus the opaque local Evidence path. The
adapter must bind the exact `id` parsed from successful `task create` stdout
and the exact `run_id` parsed from successful `verify` stdout to the original
root. IDs alone are not portable across repositories. Before every later Core
operation, the adapter must resolve the selected repository root again and
stop if it differs. It must not infer a latest Task or Run, scan for the newest
Evidence directory, or persist its own lifecycle state. A later or new
conversation requires explicit identities.

A nonzero command result stops the covered sequence. Partial stdout is not a
result. Successful public `verify` stdout continues to supply exactly `run_id`
and `evidence_path`; extending it would break the published adapter contract
and mix Evidence recording with a state query. The source Seal Legacy Plugin
`0.3.0-dev.0` resolves the canonical repository again after successful
verification, checks the retained Task, returned Run, and repository binding,
and issues exactly one read-only command without another question:

```text
seal-legacy run show <TASK_ID> --run-id <RUN_ID>
```

The Plugin accepts exit-zero stdout only when it is the exact
`validated-run-summary/v1` object documented above: exact top-level, check, and
Scope-violation key sets; integer schema version 1; exact retained identities;
and the documented field types. JSON object ordering is not semantic. Missing
or unknown keys, invalid JSON, a non-object envelope, identity mismatch, or an
invalid type is an adapter contract failure. The Plugin stops without guessing,
coercing, retrying, repairing, creating a replacement Run, or falling back to
raw Evidence. It never reads raw `verification.json` to report stored state or
choose a lifecycle operation.

A valid stored Run with a required-check failure, timeout, Scope violation, or
source instability still returns `run show` exit 0. The Plugin displays the
canonical repository, retained identities, opaque Evidence path from `verify`,
Evidence SHA-256, mechanical result, Scope state and violations, required-check
state, source stability, and every check state. It then routes only on the
adopted saved Task's `verifier.required` profile; the validated mechanical
state never changes the Basic or Reviewed branch.

Every nonzero stop and every successful pause or handoff includes a
compact failure or handoff capsule before raw diagnostics. A failure capsule
names the failed stage, exact command and exit code, identity retained only from
earlier successful stdout, later operations not run, and the next safe explicit
user decision. It must not imply that a retry is authorized. When valid
identity exists, a resume capsule gives the canonical repository root, exact
Task and Run IDs when available, opaque Evidence and bundle paths when
available, saved profile, and the exact permitted resume request. The capsule
is presentation only and is not persisted adapter state. In a new
conversation, the user must explicitly supply the repository, Task ID, and Run
ID from that capsule.

A nonzero `run show` result uses `Status: Seal Legacy stopped` and identifies `run
show` as the failure stage. The Plugin reports the exact command, stdout,
stderr, and exit code; preserves only repository, Task, Run, and Evidence
identity already obtained from successful earlier stdout; and does not run a
bundle, Verdict operation, or `complete`. It does not retry, repair, create a
new Run, or use raw Evidence as a fallback. Core exit 2 retains input/identity
meaning, exit 3 retains repository meaning, and exit 8 retains missing,
corrupt, unsupported, or unsafe Evidence meaning. `run show` does not use
completion-policy exits 4–7 or 9. An invalid exit-zero envelope stops at the
separate `run show adapter contract` stage with the same downstream boundary.

For `verifier.required=false`, the basic profile proceeds directly to final
confirmation without creating a bundle, even when the valid stored mechanical
state is failed. The adapter shows the exact completion command but does not
execute it. For `verifier.required=true`, the reviewed profile exports exactly
one approved local bundle to a fresh absolute output directory outside the
target repository after `run show`, even when that valid summary contains a
failed state, and then pauses for a separately prepared Verdict. When an
adapter-level bundle request omits an output path,
the adapter selects the same kind of fresh external directory and passes it
through Core's required `--output` argument; for an existing Run, that bundle
still requires an explicit request. Bundle preparation validates the stored
Run's integrity, but a successful export does not establish mechanical pass or
completion eligibility. It does not run or select a reviewer.

The explicit `$seal-legacy:verify` escape hatch performs only its bounded sequence:
the existing version, repository, and exact Task preflight; one `verify`; one
`run show` for the returned identity; then an Evidence identity and validated
stored-state report or exact failure. It stops without a bundle, Verdict,
completion, repair, retry, or replacement Run.

The reviewed-profile handoff capsule states that it is awaiting a separately
prepared Verdict, identifies the bundle export as containing historical S0/S1
Evidence, and gives the exact request for recording that supplied Verdict. It
does not select a reviewer, transmit the bundle, or claim that review occurred.

The implementation conversation must not create a Verdict and claim
independence. A person or a clean context using only the bundle may supply
Verdict JSON for an explicitly requested Core record operation. If the adapter
materializes inline Verdict JSON, the input file must be outside the target
repository. It must not move or delete a repository-local Verdict automatically
because that would mutate product source again. After a separately supplied
Verdict is successfully recorded, the adapter may proceed to final confirmation
without requiring the user to copy the retained identities again.

Immediately before `complete`, the adapter must show the exact repository,
Task, and Run identities and ask for final confirmation. The initial managed
confirmation never authorizes `complete`. The adapter may show the saved Task's
`verifier.required` setting, but it must not claim a recorded Verdict state
without a separately requested `verifier show`. Core alone evaluates stored
Evidence, any recorded Verdict, current S2, source binding, and completion
policy. A nonzero operation stops without repair, alternate path selection,
replacement Evidence, another Run, reverification, retry, or rollback.

## Unsupported dependencies

An adapter must not depend on any of the following:

- modules inside `src/seal_legacy` or direct Python imports
- private functions, Python exception classes, or undocumented dataclasses
- internal Git commands or subprocess implementations
- undocumented Evidence fields, temporary filenames, or atomic-write implementations
- test fixtures, repository-local prompt overrides, or editable installs from a development environment

This separation keeps Core's responsibility for deterministic local Evidence
distinct from an adapter's UI, model, network, credential, and retry policies.
Seal Legacy Core (Python) does not call model APIs or external verifier CLIs.
See [Migrating verification Evidence to v0.2](migration-v0.2.md) for the
historical Evidence boundary.
