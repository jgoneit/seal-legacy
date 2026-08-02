---
name: verify
description: Run one Harness verification for an explicitly identified existing Task and report the saved mechanical outcome. Use only when the user invokes $harness:verify; never repair, retry, bundle, or complete automatically.
---

# Harness Verify escape hatch

Activate only for the namespaced invocation. If the exact Task ID is missing,
stop this turn. Ask the user to invoke `$harness:verify` again with the missing
ID; do not rely on an untagged reply.
Perform only the requested Core operation. Require the exact Task ID; never
infer a latest Task or resume a managed lifecycle implicitly.

Run `harness --version` and support Core `>=0.2.0,<0.3.0`. Do not install a
missing or unsupported Core. From the confirmed target Git repository with a
current HEAD, run `harness task show <TASK_ID>` before verification. Use only
the public CLI, stdout JSON, stderr, exit codes, and documented read-only
artifacts. Do not import Core or reproduce Evidence interpretation.

Run exactly once per explicit request and do not pass `--base-ref`:

~~~bash
harness verify <TASK_ID>
~~~

A nonzero exit is failure. Ignore partial stdout and any partial Evidence
directory. On exit 0, report the exact `run_id` and `evidence_path`, then relay
only the stored `mechanical_result`, `scope_pass`, `required_checks_pass`, and
`source_stable_during_checks` fields from documented `verification.json`.
Evidence recording success is not a mechanical pass.

Do not repair source, replace Evidence, create a replacement Run, retry
verification, prepare a bundle, or request completion automatically. Report
the stored result or exact failure and stop.
