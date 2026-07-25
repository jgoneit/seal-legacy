---
name: harness
description: Use the Harness Core CLI to define Tasks, capture verification Evidence, prepare verifier bundles, record Manual Verdicts, and evaluate explicit completion requests.
---

# Harness

Use this Skill only as a thin adapter over the Harness Core CLI. Core is the
verification authority; the Skill does not reimplement or reinterpret it.

## Activation

Use this Skill only when the user explicitly invokes `$harness` or asks to:

- create or inspect a Harness Task;
- verify a Task;
- prepare a verifier bundle;
- record or show a Manual Verdict; or
- complete a Task.

Do not trigger Core operations automatically during ordinary coding work, and
do not direct the coding Agent's implementation process.

## Preflight

Before every Core operation, run:

~~~bash
harness --version
~~~

Support Core `>=0.2.0,<0.3.0`. If the command is missing, do not install it
automatically. Direct the user to the repository README Installation section
and stop the requested Core operation. If the version is unparseable or
unsupported, show the actual output and stop.

Run Core commands only as subprocesses. Depend only on documented commands,
stdout JSON, stderr, and exit codes. Do not import Core internals or reproduce
Task validation, check execution, Evidence generation, digest calculation, Run
validation, Verdict validation, source binding, or completion policy.

Run commands from the target Git repository. Confirm that the repository and
current HEAD exist. For an existing Task operation, also run:

~~~bash
harness task show <TASK_ID>
~~~

Before Task creation, confirm `.harness/checks.json` exists. Do not create
configuration, Tasks, Evidence, or Verdict files merely to satisfy preflight.

## Task

Collect only `id`, `type`, `objective`, `scope`, `checks`, `risk`, and
`verifier.required`. Describe the intended outcome, not the implementation
process. Show the draft Task JSON first. After the user requests creation, run:

~~~bash
harness task create --file <TASK_JSON>
~~~

## Verify

Run verification only when requested:

~~~bash
harness verify <TASK_ID>
~~~

Report only the documented `run_id` and `evidence_path` from successful stdout.
Do not pass `--base-ref`, inspect S0/S1, or treat Evidence recording as
completion.

## Bundle

~~~bash
harness verifier bundle <TASK_ID> --run-id <RUN_ID> --output <OUTPUT_DIR>
~~~

Report the bundle path. State that export does not execute a reviewer, create a
Verdict, collect S2, or complete the Task.

## Manual Verdict

Do not present a Verdict created in the implementation conversation as
independent verification. A person, a clean-context thread using only the
bundle, or the user may provide the Verdict JSON. Record or show it only through
Core:

~~~bash
harness verifier record <TASK_ID> --run-id <RUN_ID> --file <VERDICT_JSON>
harness verifier show <TASK_ID> --run-id <RUN_ID>
~~~

## Complete

Run completion only when the user explicitly requests it:

~~~bash
harness complete <TASK_ID> --run-id <RUN_ID>
~~~

Report Core stdout, stderr, and exit code. On failure, do not alter source or
Evidence, generate a replacement Run, verify automatically, retry, or roll
back. Core validates stored v2 Evidence, collects current S2, and applies its
source-binding and completion policy.

## Exclusions

Do not add hooks, approvals, plan hashes, state machines, tool interception,
implementation monitoring, worktree orchestration, subagent topology, repair
loops, automatic verify or complete, model API calls, or external verifier
invocation.
