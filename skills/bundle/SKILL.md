---
name: bundle
description: Export one explicitly identified saved Task and Run as a portable verifier bundle. Use only when the user invokes $seal:bundle; do not execute a reviewer, create a Verdict, collect S2, or complete.
---

# Seal Bundle escape hatch

Activate only for the namespaced invocation. If the exact Task ID, Run ID, or
target repository is missing, stop this turn. Ask the user to invoke
`$seal:bundle` again with the missing input; do not rely on an untagged reply.
Perform only the requested Core operation. Require exact Task and Run IDs. Do
not infer the latest Run or enter another lifecycle step.

Run `harness --version` and support Core `>=0.3.0.dev0,<0.4.0`. Do not install a
missing or unsupported Core. From the confirmed target Git repository with a
current HEAD, run `harness task show <TASK_ID>` before export. Use only the
public CLI, stdout JSON, stderr, and exit codes; do not import Core or assemble
a bundle from Evidence files yourself.

An omitted output path is not missing input. If the user omits it, choose a
unique absolute output path outside the confirmed target repository whose final
directory does not already exist, and pass it through Core's required
`--output` argument. If the user supplies a path, require the same external,
absolute, and non-existing-final-directory conditions. If it conflicts with
those conditions, stop and ask for a corrected namespaced request; do not
replace the supplied path silently. Then run once:

~~~bash
harness verifier bundle <TASK_ID> --run-id <RUN_ID> --output <OUTPUT_DIR>
~~~

Report the successful Core JSON and bundle path. State that the bundle contains
integrity-validated historical S0/S1 Evidence, but bundle success does not mean
a mechanical pass or completion eligibility. It does not run a reviewer,
create a Verdict, collect S2, or complete. Inspect check logs before external
sharing. On failure, report stdout, stderr, and exit code, then stop without
changing Evidence, selecting another Run, retrying, or chaining another
operation.
