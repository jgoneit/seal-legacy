---
name: verify
description: Run one Outcome Harness Core verification for an explicitly identified existing Task, show that exact Run once through Core's validated summary, report the Evidence identity and stored state, then stop. Use only when the user invokes $seal:verify; never repair, retry, bundle, create a Verdict, or complete automatically.
---

# Seal Verify escape hatch

Activate only for the namespaced invocation. If the exact Task ID is missing,
stop this turn. Ask the user to invoke `$seal:verify` again with the missing ID;
do not rely on an untagged reply. Perform only the requested bounded Core
sequence. Require the exact Task ID; never infer a latest Task or Run or resume
a managed lifecycle implicitly.

Run `harness --version` and support Core `>=0.3.0.dev0,<0.4.0`. Do not install a
missing or unsupported Core. From the confirmed target Git repository with a
current HEAD, resolve and retain the canonical root, then run exactly one
preflight lookup:

~~~bash
harness task show <TASK_ID>
~~~

Require successful Task stdout to identify the exact requested Task. Use only
the public CLI, stdout JSON, stderr, and exit codes. Do not import Core or
reproduce Evidence interpretation.

Run exactly once per explicit request and do not pass `--base-ref`:

~~~bash
harness verify <TASK_ID>
~~~

A nonzero exit is failure. Ignore partial stdout and any partial Evidence
directory. On exit 0, require stdout to be one JSON object with exactly
`run_id` and `evidence_path`, both non-empty strings. Retain that exact Run ID
and opaque Evidence path with the requested Task ID and canonical repository.
Lead with `Status: Evidence recorded`; Evidence recording success is not a
check pass, stored mechanical pass, completion acceptance, or completion
eligibility.

Without another question, resolve the canonical repository root again and
require it to equal the retained root. For the retained Task ID and the exact
Run ID returned by `verify`, run exactly once:

~~~bash
harness run show <TASK_ID> --run-id <RUN_ID>
~~~

Do not read `<evidence_path>/verification.json` to report an outcome or choose
a later operation. Public `verify` stdout does not expose an
integrity-validated mechanical summary; public `run show` does so only after
Core's canonical stored-Run validation. Do not call `validate_run()` directly
or interpret raw Evidence as a fallback.

On exit 0, accept stdout only as the exact `validated-run-summary/v1` shape;
that contract name is not another JSON field. Ignore JSON object key ordering,
but require exactly these top-level keys: `checks`, `evidence_sha256`,
`mechanical_result`, `required_checks_pass`, `run_id`, `schema_version`,
`scope_pass`, `scope_violations`, `source_stable_during_checks`, and `task_id`.
Require integer `schema_version` 1, not a boolean; retained string identities;
exactly 64 lowercase hexadecimal characters for `evidence_sha256`;
`mechanical_result` equal to `pass` or `fail`; boolean pass and stability
fields; and array values for checks and Scope violations.

Every check object must have exactly `exit_code`, `name`, `passed`, `required`,
and `timed_out`, with a string name, boolean state fields, and an integer other
than a boolean or null exit code. Every Scope violation must have exactly
`path`, `previous_path`, `source`, and `status`, with string `path`, `source`,
and `status`, and string or null `previous_path`. Missing or unknown keys,
invalid JSON, a non-object envelope, identity mismatch, or any wrong type is an
adapter contract failure. Do not guess, coerce, retry, repair, replace the Run,
or fall back to raw Evidence.

After a valid summary, report the canonical repository, exact Task and Run IDs,
opaque Evidence path, Evidence SHA-256, mechanical result, Scope pass and exact
violations, required-check pass, source stability, and each check's
required/passed/timed-out/exit-code state. State separately that `verify` exit 0
recorded Evidence, `run show` exit 0 validated stored Run integrity and
serialized the summary, and `mechanical_result=pass` is only stored mechanical
state. None means completion acceptance or eligibility. A valid failed check,
timeout, Scope violation, or source instability remains stored state returned
with `run show` exit 0; report it and stop.

If either command exits nonzero, report `Status: Seal stopped`, the exact
failure stage and command, stdout, stderr, and numeric exit code, then stop. For
`run show`, preserve only the Task/Run/Evidence identity obtained from the
successful earlier commands. Preserve exit 2 for input or identity, 3 for
repository, and 8 for missing, corrupt, unsupported, or unsafe Evidence;
`run show` does not use completion-policy exits 4–7 or 9. Treat an invalid
success envelope as `Failure stage: run show adapter contract` and apply the
same stop boundary.

Do not repair source, replace Evidence, create a replacement Run, retry
verification, repeat `run show`, prepare a bundle, record or show a Verdict, or
request or execute completion. Report the exact Evidence identity and validated
stored state, or the exact failure, and stop.
