---
name: harness
description: Manage a Harness workflow for a coding outcome by drafting and adopting a Task, creating it, letting the coding Agent implement freely, running one pre-approved verification, reporting saved Evidence, optionally preparing a reviewed-profile bundle, and requesting final confirmation before completion. Use only for an explicit $harness end-to-end request or an unambiguous confirmation or resume reply in the same conversation after this Skill requested it; never start Harness during ordinary coding work.
---

# Harness managed workflow

This Skill orchestrates conversation UX over public Harness Core commands. Core
remains the only authority for Task normalization, Evidence, Verdict validation,
source binding, and completion. The workflow does not monitor or authorize
implementation steps.

## Activation

Treat `$harness <work request>` as an explicit request for the managed workflow
below. An unambiguous direct reply to this Skill's own first or final
confirmation, drift re-adoption or new-Task choice, or request for a separately
prepared Verdict may resume the same workflow in the same conversation. Do not
treat an unrelated approval or ordinary coding request as activation. Within
an activation case above, if the user requests only one operation on an
existing Task or Run, perform that one operation and do not silently enter the
managed workflow.

Task Scope describes what the completion claim covers; it is not a write
permission or tool gate. Normal host and client permission prompts remain
separate from this conversational workflow.

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

Confirm that the target Git repository and current HEAD exist. Before Task
creation, confirm `.harness/checks.json` exists. Before an operation on an
existing Task, run:

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
implementation process. Show all of the following before asking for adoption:

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
implementation, and the first `verify` exactly once, plus one conditional
bundle export for a mechanically passing reviewed profile. Show the exact
Task draft and the covered actions when asking.

This confirmation does not authorize `complete`. It is not an exact-word
protocol, approval token, Plan hash, or substitute for host or client
permission prompts. If the user declines or materially changes the Task,
revise the draft and ask again before any Core write.

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
that adopting it covers ordinary implementation, the first `verify` exactly
once, and the same conditional reviewed-bundle preparation. Restate that it
does not authorize `complete`, and continue only after confirmation.

Keep the exact Task ID in the same conversation so the user does not need to
copy it. Do not select a latest Task or Run, scan for the newest directory, or
persist conversational lifecycle state. In a new conversation, require the
exact Task and Run IDs instead of carrying them forward.

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
`evidence_path`. Treat the returned path as opaque and local to the same host
and repository. Read only the documented `<evidence_path>/verification.json`
for display, and relay its stored `mechanical_result`, `scope_pass`,
`required_checks_pass`, and `source_stable_during_checks` fields without
recalculating or reinterpreting them. Exit 0 means Evidence was recorded; it
does not mean the mechanical outcome passed.

Do not repair source, replace Evidence, create a replacement Run, or retry
verification after either a nonzero `verify` result or
`mechanical_result="fail"`. Report the exact Task ID, Run ID when available,
Evidence path when available, stored result fields, stderr, and exit code, then
stop the managed flow.

## Prepare reviewed Evidence when required

For `verifier.required=true`, prepare a bundle only when the stored mechanical
result passes. The first confirmation covers this one conditional export. Use
a unique absolute output path outside the target repository whose final
directory does not already exist:

~~~bash
harness verifier bundle <TASK_ID> --run-id <RUN_ID> --output <OUTPUT_DIR>
~~~

Report the exact IDs and bundle path. Bundle export validates and copies
historical S0/S1 Evidence only; it does not run a reviewer, create a Verdict,
collect S2, or complete the Task. Inspect logs before any external sharing and
never send the bundle elsewhere without an explicit user request.

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
to a Task and Run; it does not prove reviewer independence.

## Ask for final completion confirmation

For a mechanically passing basic profile, or a reviewed profile with an
eligible recorded Verdict, show the exact Task ID, Run ID, stored mechanical
summary, required Verdict state, and exact command. Ask for a separate final
confirmation immediately before `complete`:

~~~bash
harness complete <TASK_ID> --run-id <RUN_ID>
~~~

The initial confirmation does not authorize `complete`. Final confirmation
authorizes only this one evaluation; Core, not the confirmation, decides
completion. Repeat preflight, run the exact command once, and report Core
stdout, stderr, and exit code.

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
