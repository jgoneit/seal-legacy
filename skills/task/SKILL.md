---
name: task
description: Create or inspect one Harness Task as an explicit low-level operation. Use only when the user invokes $harness:task for Task drafting, creation, adoption, or lookup; do not continue into implementation or verification.
---

# Harness Task escape hatch

Activate only for the namespaced invocation. If required input or Task adoption
is missing, stop this turn. Ask the user to invoke `$harness:task` again with
the missing input or confirmation; do not rely on an untagged reply.
Perform only the requested Core operation. Do not continue into implementation,
verification, bundle export, Verdict handling, or completion.

Before every operation, run `harness --version` and support Core
`>=0.2.0,<0.3.0`. Do not install a missing or unsupported Core. Run commands as
subprocesses from a confirmed target Git repository with a current HEAD. Do not
import Core or reproduce its validation.

For creation, confirm `.harness/checks.json` exists. Draft only
`schema_version`, `id`, `type`, `objective`, `scope`, `checks`, `risk`, and
`verifier.required`. Show the draft plus a catalog-derived check preview with
`argv` and `required`, and show `timeout_seconds` when present. Label the checks
as a preview rather than Core normalization. When omitted, mark the timeout as
omitted and let Core apply its behavior; do not infer a numeric default. Also
show the HEAD baseline semantics and existing dirty changes. Task Scope is a
completion-claim boundary, not a write permission.

After explicit adoption, write the temporary input outside the target
repository and run once without `--force`:

~~~bash
harness task create --file <TASK_JSON>
~~~

For lookup, require an exact ID and run:

~~~bash
harness task show <TASK_ID>
~~~

Report successful stdout JSON exactly, including the authoritative normalized
checks from successful `task create` stdout. On any failure, report stdout,
stderr, and exit code, then stop. Do not overwrite a Task, infer a latest Task,
alter source, create Evidence, or retry automatically.
