---
name: harness
description: Manage a Harness workflow for a coding outcome by drafting and adopting a Task, creating it, letting the coding Agent implement freely, running one pre-approved verification, preparing one conditional reviewed-profile bundle, and carrying the exact Evidence identity to a separately confirmed completion evaluation. Use only for an explicit $harness end-to-end request, an explicitly selected @Harness Plugin paired with an executable coding outcome, or an unambiguous confirmation or resume reply in the same conversation after this Skill requested it; never start Core for ordinary coding, discussion, planning, audit, review, or status requests.
---

# Harness managed workflow

This Skill orchestrates conversation UX over public Harness Core commands. Core
remains the only authority for Task normalization, Evidence, Verdict validation,
source binding, and completion. The workflow does not monitor or authorize
implementation steps.

## Activation

Start the managed workflow only when `$harness` or an explicitly selected
`@Harness` Plugin is paired with an executable end-to-end coding outcome. The
invocation form never overrides that outcome requirement: Plugin selection
alone and Harness discussion, explanation, planning, audit, review, or status
requests do not activate Core. An
unambiguous direct reply to this Skill's own first or final confirmation, drift
re-adoption or new-Task choice, or an explicit request to use the carried
identity for a bundle, separately prepared Verdict, or completion may resume
the same workflow in the same conversation. Do not treat an unrelated approval
or ordinary unselected coding request as activation. Within an activation case
above, if the user requests only one operation on an existing Task or Run,
perform that one operation and do not silently enter the managed workflow.

Task Scope describes what the completion claim covers; it is not a write
permission or tool gate. Normal host and client permission prompts remain
separate from this conversational workflow.

## User-facing presentation

Lead with a compact status summary before the contract detail. For a Harness
discussion, explanation, plan, audit, review, or status request that does not
activate Core, state `Mode: Analysis only` and that Core was not started. For an
activated coding outcome, state `Mode: Managed execution` and show the current
status, canonical repository, saved profile when known, and next action. Run
the read-only version, repository, HEAD, and check-catalog preflight before
drafting the Task so setup failures do not lead to an adoption prompt.

For every first-adoption response, render these blocks in this exact
top-to-bottom order. Do not interleave them or move a later block ahead of an
earlier block:

1. `Mode: Managed execution` and the current `Status`;
2. a compact summary containing the canonical repository, outcome, Scope, HEAD
   baseline, check names, profile, next action, and existing working-tree state
   grouped as staged, unstaged, and untracked, or `Working tree: clean`;
3. `Included in this confirmation`;
4. `Not included in this confirmation`;
5. `Local records`;
6. `Task draft:` followed by the full Task JSON;
7. the catalog-derived check preview; and
8. one adoption question.

The Task JSON and check preview must not appear before the dirty-tree
disclosure or any of the three approval-boundary labels. The three approval
labels mean:

- `Included in this confirmation`: Task creation, ordinary implementation, the
  first `verify` exactly once, and the reviewed profile's one conditional local
  bundle when applicable;
- `Not included in this confirmation`: Verdict record/show, reviewer
  invocation, external sharing, and `complete`; and
- `Local records`: the Task snapshot and any later Evidence or bundle paths
  that the covered operations may create.

Progressive disclosure must not omit or weaken any exact draft, argv, timeout,
baseline, or dirty-tree disclosure that this Skill requires. These display
labels are presentation only and are not persisted lifecycle state, Core
results, approvals, or additional authority.

If `harness --version` is missing, unparseable, or unsupported, lead with
`Status: Core unavailable`, state that the Plugin and Core are installed
separately, report the actual command result, point to the README Installation
section, and name the original managed request as the request to repeat after
compatible Core is available. Do not imply that a Task draft, Task, or Run was
created.

After `verify` exits zero, lead with `Status: Evidence recorded`. This must not
be described as verification passed; immediately state that Evidence recording
does not mean that checks passed or that completion is eligible. After a bundle
export, describe it as a review handoff export, not a review result. Describe
completion only from the exact `complete` result as accepted or refused.

## Core boundary and preflight

Before every Core operation, run:

~~~bash
harness --version
~~~

Support Core `>=0.2.0,<0.3.0`. If the command is missing, do not install it
automatically. Direct the user to the repository README Installation section
and stop the requested Core operation. If the version is unparseable or
unsupported, show the actual output and stop.

Run Core only as a subprocess from the target Git repository. Depend only on
documented commands, stdout JSON, stderr, exit codes, and documented read-only
artifacts. Do not import Core internals or reproduce Task validation, check
execution, Evidence generation, digest calculation, Run validation, Verdict
validation, source binding, or completion policy.

Confirm that the target Git repository and current HEAD exist. Resolve and
retain its canonical repository root before Task creation. Before every later
Core operation, resolve the selected repository root again and compare it with
the retained root. If it differs from the retained root, stop without running
Core. Do not reuse or search for those IDs in another repository.

Before Task creation, confirm `.harness/checks.json` exists. Before an operation
on an existing Task, run:

~~~bash
harness task show <TASK_ID>
~~~

Do not create configuration, Tasks, Evidence, or Verdict files merely to
satisfy preflight.

Any nonzero Core command result stops the covered sequence. Report stdout,
stderr, and exit code. Do not consume partial stdout, retry the operation,
select an alternate output path or identity, or chain the next operation.

## Draft the Task

Collect only `schema_version`, `id`, `type`, `objective`, `scope`, `checks`,
`risk`, and `verifier.required`. Describe the intended outcome, not the
implementation process. Set `type` to exactly one public Task Schema value:
`bugfix`, `feature`, `refactor`, `test`, `docs`, or `config-infra`. Use `docs`
when the outcome changes documentation only. Do not invent another label such
as `implementation`, `maintenance`, or `chore`. This draft guidance does not
replace Core validation. Show all of the following before asking for adoption:

- the draft Task JSON;
- a catalog-derived check preview with `argv` and `required`, plus
  `timeout_seconds` when present. Label it as a preview rather than Core
  normalization. When a timeout is omitted, show it as omitted and let Core
  apply its behavior; do not infer a numeric default;
- that the Task baseline will be the current HEAD; and
- a short summary of existing staged, unstaged, and untracked changes.

The baseline is current HEAD, not the current working tree. Existing changes
may enter the Evidence Run. Disclose and preserve them; do not stash, reset,
commit, delete, widen Scope, or otherwise absorb them automatically. Pause
before adoption when ownership or Scope is unclear.

Write the temporary Task input JSON outside the target repository so that the
draft cannot become product Evidence. Never pass `--force`.

## Ask for the first confirmation

Ask for one conversational confirmation that covers Task creation, ordinary
implementation, and the first `verify` exactly once. Show the exact Task draft
and the covered actions when asking. If the draft uses the reviewed profile,
also show that the same confirmation covers exactly one local bundle export
after successful Evidence recording, using a fresh absolute output directory
outside the target repository. That conditional export is covered if and only
if the adopted saved Task has `verifier.required=true`.

This confirmation does not authorize Verdict record/show, reviewer invocation,
external sharing, or `complete`. It is not an exact-word protocol, approval
token, Plan hash, or substitute for host or client permission prompts. If the
user declines or materially changes the Task, revise the draft and ask again
before any Core write.

## Create and carry the Task identity

After confirmation, run:

~~~bash
harness task create --file <TASK_JSON>
~~~

Capture the exact successful `task create` stdout `id`, baseline, and checks.
Treat only the authoritative normalized checks from successful `task create`
stdout as Core's saved result. If Task creation fails, report stdout, stderr,
and exit code, then stop without implementing or verifying.

Compare the saved `id`, `type`, `objective`, `scope`, `risk`, and `verifier`
fields with the approved draft, compare the saved baseline with the displayed
HEAD, and compare the saved check `name`, `argv`, `required`, and optional
`timeout_seconds` presence and value with the approved preview. If the saved
Task fields differ from the approved draft, the saved baseline differs from the
displayed HEAD, or the saved checks differ from the approved preview, show the
exact difference. Preserve the created Task and stop before implementation or
verification. Require a new explicit adoption confirmation for that exact
saved Task, or draft a new Task with a new ID; do not overwrite the created
Task or treat the first confirmation as covering the difference.
When asking for re-adoption, show the exact saved Task and checks, and restate
that adopting it covers ordinary implementation and the first `verify` exactly
once. If the exact saved Task has `verifier.required=true`, restate that it also
covers exactly one local bundle export to a fresh absolute directory outside
the target repository. Restate that it does not authorize Verdict record/show,
reviewer invocation, external sharing, or `complete`, and continue only after
confirmation.

Bind the exact Task ID to the retained canonical repository root in the same
conversation so the user does not need to copy it. Do not select a latest Task
or Run, scan for the newest directory, or persist conversational lifecycle
state. In a new conversation, require the exact repository, Task ID, and Run ID
instead of carrying them forward.

## Let the coding Agent implement

Use normal coding-agent judgment, tools, tests, and iteration. Harness does not
prescribe tool order, implementation method, worktree strategy, or subagent
topology. The one-Run limit applies to `harness verify`, not ordinary
development tests.

If implementation is blocked or aborted, do not consume the approved
verification. If the objective, Scope, checks, or verifier requirement must
materially change after Task creation, do not overwrite the Task; stop and ask
whether to create a new Task.

## Verify exactly once

When there is a completion candidate, repeat preflight and show the captured
Task. Then run exactly once, without another Harness confirmation because the
first confirmation covered it:

~~~bash
harness verify <TASK_ID>
~~~

Do not pass `--base-ref`. A nonzero `verify` result is a failed command even if
a partial Evidence directory or stdout exists. Do not consume partial stdout
as a result.

On exit 0, capture the exact successful `verify` stdout `run_id` and
`evidence_path`, and bind the returned Run ID and opaque Evidence path to that
same root. Treat the path as local to the same host and repository. Report the
exact `run_id` and `evidence_path` together with the Task ID, stderr, and exit
code.

Do not read `<evidence_path>/verification.json` to report an outcome or decide
what to do next. Core `0.2.x` public `verify` stdout does not expose an
integrity-validated mechanical summary, and a direct artifact read does not
pass through Core's canonical stored-Run validator. Exit 0 means Evidence was
recorded; it does not mean the mechanical outcome passed. Branch only on the
adopted saved Task's `verifier.required` field; do not inspect raw Evidence to
choose the branch.

When `verifier.required=false`, do not create a bundle. Continue immediately to
the final completion confirmation below, show the exact command, and ask for
that confirmation without running it.

When `verifier.required=true`, create exactly one approved local bundle after
repeating preflight. Select a unique absolute output path outside the target
repository whose final directory does not already exist, then run:

~~~bash
harness verifier bundle <TASK_ID> --run-id <RUN_ID> --output <OUTPUT_DIR>
~~~

Report the exact IDs, Evidence path, and bundle path. Bundle success does not
mean a mechanical pass or completion eligibility. It validates stored-Run
integrity and copies historical S0/S1 Evidence; it does not run a reviewer,
create a Verdict, collect S2, or complete the Task. Inspect logs before any
external sharing and never send the bundle elsewhere without an explicit user
request. Pause for a separately prepared Verdict.

After a successful managed `verify` or conditional bundle, do not repair
source, replace Evidence, create a replacement Run, retry verification, or
prepare another bundle. A nonzero `verify` or bundle follows the global
fail-stop rule and never proceeds to another operation.

## Prepare reviewed Evidence

For a newly created managed Task, the previous section creates the reviewed
profile's one bundle only when the first confirmation covered it. Do not create
a second bundle. For an existing Task or Run, or an explicit single-operation
request, prepare one bundle only after a new explicit request. Do not infer
bundle eligibility from raw Evidence artifacts. Use the same fresh external
output-path rule and Core command shown above.

The implementation conversation must not create a Verdict and claim it is
independent. A person, the user, or a genuinely clean-context review using only
the bundle may prepare Verdict JSON. Pause until such a Verdict is supplied.
Record or show that separately supplied Verdict only through Core and only on
an explicit request to resume:

~~~bash
harness verifier record <TASK_ID> --run-id <RUN_ID> --file <VERDICT_JSON>
harness verifier show <TASK_ID> --run-id <RUN_ID>
~~~

Keep the Verdict input outside the target repository. If the user supplies
inline Verdict JSON, materialize it only as a temporary file outside the target
repository. If the user instead points to a repository-local Verdict, stop and
explain that creating or changing it after verification can change S2. Do not
move or delete a repository-local Verdict automatically.

Do not overwrite an existing Verdict silently. Core binds a recorded Verdict
to a Task and Run; it does not prove reviewer independence. After a separately
supplied Verdict is successfully recorded for the retained managed identity,
continue immediately to the final completion confirmation. Run `verifier show`
only when explicitly requested.

## Report failures and handoffs

For every blocked, aborted, or nonzero Core stop, lead with a compact failure
summary before the raw stdout and stderr:

- `Status: Harness stopped`;
- `Failure stage`: the operation that did not complete;
- `Core result`: the exact command, exit code, and whether stdout or stderr was
  empty when a Core command ran, or `not run` plus the reason when none ran;
- `Preserved identity`: only the canonical repository, Task ID, Run ID, and
  opaque paths obtained from earlier successful Core stdout;
- `Not run`: every covered later operation that was not executed; and
- `Next explicit request`: the next safe user decision, or a statement that no
  retry is authorized within this managed sequence.

Do not put partial stdout, a partial Evidence directory, an inferred latest ID,
or a proposed replacement Run in `Preserved identity`. The summary must not
imply that a retry, repair, or replacement operation is authorized.

When a valid carried identity exists at a pause or successful handoff, add a
copyable `Resume capsule` containing the canonical repository root, exact Task
ID, exact Run ID when available, opaque Evidence path when available, saved
profile, bundle path when available, and the exact resume request permitted by
the current lifecycle boundary. This capsule is presentation only; it does not
persist state or activate another operation.

For a reviewed-profile bundle handoff, label the state `Status: Review handoff
ready`, include `Awaiting a separately prepared Verdict`, identify the bundle
export as containing historical S0/S1 Evidence, and provide the exact resume
request for recording that separately supplied Verdict. Do not select a
reviewer, send the bundle, or claim review independence.

## Ask for final completion confirmation

Enter this section after successful managed verification for a basic profile,
after a separately supplied Verdict is successfully recorded for a reviewed
profile, or after an explicit completion request for an existing identity.
Show the retained canonical repository root, exact Task ID, exact Run ID, the
saved Task's `verifier.required` setting, and exact command. Do not inspect or
claim a recorded Verdict state unless the user separately requested
`verifier show`. Ask for a separate final confirmation immediately before
`complete`:

~~~bash
harness complete <TASK_ID> --run-id <RUN_ID>
~~~

The initial confirmation does not authorize `complete`. Final confirmation
authorizes only this one evaluation; Core, not the confirmation, decides
completion. Never run `complete` without the separate final confirmation.
Repeat preflight, run the exact command once, and report Core stdout, stderr,
and exit code.

On failure, do not alter source or Evidence, create another Run, reverify,
retry completion, or roll back. Report the refusal and stop.

## Explicit single-operation mode

Within an activation case above, perform only the explicitly requested public
Core operation for a request concerning an existing Task or Run. Require exact
IDs, repeat preflight, preserve the same failure stops, and do not chain
implementation, verification, bundle, Verdict, or completion operations unless
the user explicitly resumes the managed workflow.

## Exclusions

Do not add hooks, runtime approval state, Plan hashes, state machines, tool
interception, implementation monitoring, worktree orchestration, credential
handling, repair loops, external reviewer invocation, or model API calls.
