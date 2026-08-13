---
name: complete
description: Evaluate completion for one explicitly identified Outcome Harness Core Task and Run after final confirmation. Use only when the user invokes $seal:complete; never infer the latest Run or retry after failure.
---

# Seal Complete escape hatch

Activate only for the namespaced invocation. If an exact ID or final
confirmation is missing, stop this turn. Ask the user to invoke
`$seal:complete` again with the missing ID or confirmation; do not rely on an
untagged reply.
Perform only the requested Core operation. Require exact Task and Run IDs;
never infer a latest identity. An invocation that names both IDs and explicitly
asks to complete may count as the final confirmation. Otherwise show the exact
command and ask once immediately before execution.

Run `harness --version` and support Core `>=0.2.0,<0.3.0`. Do not install a
missing or unsupported Core. From the confirmed target Git repository with a
current HEAD, run `harness task show <TASK_ID>` before completion. Use only the
public CLI, stdout JSON, stderr, and exit codes; do not import Core or
reimplement stored Run, Verdict, source-binding, or completion decisions.

After final confirmation, run once:

~~~bash
harness complete <TASK_ID> --run-id <RUN_ID>
~~~

Report stdout, stderr, and exit code. Core decides whether completion is
supported. On failure, do not alter source or Evidence, create another Run,
reverify, retry, roll back, or chain another operation.
