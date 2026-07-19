---
name: harness
description: Use the Harness Core CLI to define Tasks, capture verification Evidence, prepare verifier bundles, record Manual Verdicts, and evaluate explicit completion requests without controlling how the coding Agent implements the work.
---

# Harness

Use Harness only as an explicit, thin UX adapter over the Core CLI. The Core CLI is the verification authority; this Skill must not reimplement or reinterpret it.

## Activation boundary

Use this Skill only when the user:

- explicitly invokes $harness;
- asks to create a Harness Task;
- asks to verify a Harness Task;
- asks to prepare a verifier bundle;
- asks to record or show a Manual Verdict; or
- explicitly asks to complete a Task.

For ordinary coding work, do not create a Task, run verification, prepare a bundle, record a Verdict, or complete a Task automatically.

Do not direct how the coding Agent implements work. In particular, do not prescribe implementation order, tools, subagent count, worktree structure, repair algorithms, or file-by-file implementation plans.

## Core preflight

Before every Core operation, run:

~~~bash
harness --version
~~~

Read the version from the command output. Support only Core versions >=0.1.0,<0.2.0. If the CLI is missing, do not install it automatically. Explain the missing-command error and provide this command for the user to run:

~~~bash
python3 -m pip install \
  "git+https://github.com/jgoneit/harness.git@v0.1.1"
~~~

If the version cannot be parsed or is unsupported, show the actual output and stop before the requested Core operation.

Run Core commands as subprocesses only. Depend only on documented commands, stdout JSON, stderr, and exit codes. Do not import harness.task, harness.evidence, harness.bundle, harness.run_validator, or harness.verdict_validator; do not read Core internals to decide an outcome; and do not reproduce schema validation, scope checks, Git diff collection, check execution, Evidence generation, digest calculation, Run consistency, Verdict validation, or completion policy.

## Repository preflight

Run requested Core commands from the target project's Git repository. Before every operation, confirm:

- Git repository and current HEAD exist;
- a requested Task ID exists, using harness task show TASK_ID when applicable.

Before `harness task create`, also confirm that `.harness/checks.json` exists.
Task creation reads the current catalog to materialize checks in the saved Task
snapshot.

Do not require `.harness/checks.json` for `harness verify`, `harness verifier
bundle`, `harness verifier record`, `harness verifier show`, or `harness
complete`. `harness verify` executes checks from the saved Task snapshot; the
other commands validate saved Task and Run artifacts. These operations do not
need the current catalog.

Do not generate project configuration, Tasks, Evidence, or Verdict files merely to satisfy preflight. Show Git or Core CLI errors as returned.

## Create a Task

When asked to define a Task, collect only its objective, scope, checks, risk, and verifier.required. Keep the Task description about the intended outcome, not the Agent's implementation process. Include the Core-required id and type as concise metadata.

Show a draft Task JSON first:

~~~json
{
  "schema_version": 1,
  "id": "TASK-001",
  "type": "feature",
  "objective": "…",
  "scope": ["…"],
  "checks": ["…"],
  "risk": "medium",
  "verifier": {
    "required": true
  }
}
~~~

Only after the user requests creation, write or use the chosen Task JSON file and run:

~~~bash
harness task create --file <TASK_JSON>
~~~

Do not require an approval token, a plan hash, or an exact-y response.

## Verify

Run verification only when the user requests it:

~~~bash
harness verify <TASK_ID>
~~~

Parse successful stdout as JSON and report only the documented run_id and evidence_path fields. Do not calculate, reinterpret, or add a mechanical result, digest, or completion claim.

## Prepare a verifier bundle

Run:

~~~bash
harness verifier bundle <TASK_ID> \
  --run-id <RUN_ID> \
  --output <OUTPUT_DIR>
~~~

State clearly that generating a bundle is not reviewer execution, Verdict creation, or completion. Do not inspect Core files to construct or modify a bundle yourself.

## Record or show a Manual Verdict

Do not represent a Verdict created in the same implementation conversation as independent verification. Offer these paths:

1. A person reviews the bundle directly.
2. A new clean-context Codex thread receives only the bundle.
3. The user provides a separately prepared Verdict JSON.

Record only user-provided Verdict JSON through Core:

~~~bash
harness verifier record <TASK_ID> \
  --run-id <RUN_ID> \
  --file <VERDICT_JSON>
~~~

Show a recorded Verdict through Core:

~~~bash
harness verifier show <TASK_ID> \
  --run-id <RUN_ID>
~~~

Do not reimplement the Verdict Schema. Preserve Core stderr and exit codes as the authoritative result.

## Complete

Run completion only when the user explicitly requests it:

~~~bash
harness complete <TASK_ID> --run-id <RUN_ID>
~~~

On failure, report the Core exit code and stderr. Do not roll back source, alter Evidence, repair automatically, verify automatically, or retry completion automatically. State the Core v0.1.1 limitation: completion evaluates saved Run Evidence and does not bind it to the current source state.

## Never add control-plane behavior

Do not add hooks, PreToolUse/PostToolUse or Stop hooks, approval state, plan hashes, process state machines, tool denylists, file-write interception, implementation monitoring, worktree orchestration, subagent-topology control, automatic repair, automatic verify, automatic complete, model API calls, or external verifier CLI calls.
