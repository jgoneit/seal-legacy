---
name: bundle
description: Export one explicitly identified saved Task and Run as a portable verifier bundle. Use only when the user invokes $harness:bundle; do not execute a reviewer, create a Verdict, collect S2, or complete.
---

# Harness Bundle escape hatch

Activate only for the namespaced invocation. If an exact Task ID, Run ID, or
required path decision is missing, stop this turn. Ask the user to invoke
`$harness:bundle` again with the missing input; do not rely on an untagged reply.
Perform only the requested Core operation. Require exact Task and Run IDs. Do
not infer the latest Run or enter another lifecycle step.

Run `harness --version` and support Core `>=0.2.0,<0.3.0`. Do not install a
missing or unsupported Core. From the confirmed target Git repository with a
current HEAD, run `harness task show <TASK_ID>` before export. Use only the
public CLI, stdout JSON, stderr, and exit codes; do not import Core or assemble
a bundle from Evidence files yourself.

Default to a unique absolute output path outside the target repository whose
final directory does not already exist. Then run once:

~~~bash
harness verifier bundle <TASK_ID> --run-id <RUN_ID> --output <OUTPUT_DIR>
~~~

Report the successful Core JSON and bundle path. State that the bundle contains
validated historical S0/S1 Evidence and does not run a reviewer, create a
Verdict, collect S2, or complete. Inspect check logs before external sharing.
On failure, report stdout, stderr, and exit code, then stop without changing
Evidence, selecting another Run, retrying, or chaining another operation.
