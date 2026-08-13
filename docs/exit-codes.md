# Harness exit codes

The exit codes below describe the `0.3.0.dev0` Core development line and are
part of its public CLI contract. Existing numeric meanings remain stable from
the published `v0.2.1` release.

| Code | Meaning | Typical condition |
| ---: | --- | --- |
| 0 | success | The requested command completed successfully and, for `complete`, all completion conditions were satisfied |
| 2 | invalid input or schema | Invalid CLI arguments, Task/run mismatch, or an invalid Task Spec or saved Task structure |
| 3 | git/repository error | Git execution failure, execution outside a Git repository, or an unresolvable Git baseline |
| 4 | scope violation | The stored Evidence records a change outside the product Scope |
| 5 | required check failure | A non-timeout required check failure is stored |
| 6 | timeout | A required check timeout is stored |
| 7 | verifier gate not satisfied | Required verifier Evidence is missing, or the recorded Verdict is fail/unable or contains a blocker |
| 8 | evidence missing or corrupt | Required Evidence files are missing, JSON is unreadable, the verification schema version is unsupported, or stored records contradict one another |
| 9 | source binding not satisfied | S0 differs from S1, or current S2 differs from the validated post-check S1 |

## `harness run show` state query

`harness run show <TASK_ID> --run-id <RUN_ID>` calls the canonical
`validate_run()` exactly once and returns a transient Validated Run Summary. It
does not run checks, collect S2, inspect current source, read Verdict or
completion state, write files, or infer a latest Run.

Exit 0 means that stored Run integrity was validated and the state envelope was
serialized. It applies equally to a mechanically passing Run and to a valid Run
that records a required-check failure, timeout, Scope violation, or S0/S1
instability. Those conditions appear in the JSON fields rather than changing
the command's exit code.

Invalid input or Task/Run identity is exit 2, a repository-resolution failure
is exit 3, and missing, malformed, contradictory, unsupported, or unsafe
Evidence is exit 8. The command never applies completion policy, so it does not
return exits 4–7 or 9 for valid stored state. Success has one JSON object on
stdout and empty stderr. Handled errors have empty stdout and an
`error: <message>` diagnostic on stderr; argparse errors use its normal usage
and error text on stderr.

## `harness complete` decision process

`harness complete <TASK_ID> --run-id <RUN_ID>` does not rerun checks or
regenerate the Git diff. First, the canonical `validate_run()` checks only the
stored Task/Run identity, artifact paths, check results, scope, mechanical
result, versioned Source Snapshot Evidence, and raw-byte digest integrity in
`run-manifest.json`. Completion separately collects the current product-source
Snapshot after stored Evidence and any recorded Verdict have passed their
integrity checks. `--run-id` is required; implicit latest-Run selection is not
supported.

All of the following must be true for success (exit 0):

- The requested Task and Run ID match the identity in the saved Task and `verification.json`.
- The required Evidence files and the Evidence files listed in `verification.json` exist, and JSON Evidence passes parsing and internal consistency checks.
- `run-manifest.json` matches the expected mechanical file list exactly, and each file's raw-byte size and SHA-256 and the canonical `evidence_sha256` match.
- `verification.json` is version 2, both Snapshot files are valid schema-version-1 documents, and their baselines and digests match the Task and verification records.
- The pre-check S0 and post-check S1 Snapshots are equal, so `source_stable_during_checks=true`.
- The current completion-time S2 Snapshot is equal to S1.
- `scope_pass` is `true`.
- Every required check has `passed=true` and none timed out.
- `required_checks_pass=true` and the v2 mechanical result, which also includes source stability, is `"pass"`.
- If the Task has `verifier.required` set to `true`, a valid Manual Verdict exists, the Verdict is `pass`, and it has zero blockers.
- If the Task has `verifier.required` set to `false`, the Task can complete mechanically without a Verdict. However, exit 7 is returned if a recorded Verdict is `fail` or `unable` or contains a blocker.

A required-check failure, timeout, Scope violation, source instability, or
`mechanical_result="fail"` is not itself an error from `validate_run()`. These
are validly recorded failed Runs that can still be exported as bundles or have
Manual Verdicts recorded. Only `complete` rejects them with exit 4–7 or 9
according to completion policy.

When a Verdict has been recorded, the raw Verdict and normalized snapshot must both exist, parse successfully, and match. If only one is present or either is corrupt, completion returns exit 8 even when the verifier is optional. If neither exists and the verifier is optional, mechanical-only completion remains allowed. Warning and note findings do not block `complete`; their counts are recorded in `completion.json`. A successful completion also records the `evidence_sha256` of the consumed mechanical Evidence set.

A failed completion does not create or overwrite `completion.json`. If an
earlier successful completion record already exists, a later refusal leaves
that historical record in place; it does not make the current source eligible.

The fail-closed decision order is:

1. Missing, corrupt, contradictory, or unsupported mechanical Evidence,
   including required Snapshot Evidence, returns exit 8.
2. Missing, corrupt, or contradictory recorded Verdict Evidence returns exit 8.
3. Failure to collect S2 from the current repository returns exit 3.
4. S0/S1 instability or an S1/S2 mismatch returns exit 9.
5. An unsatisfied verifier gate returns exit 7.
6. A Scope violation returns exit 4.
7. A required timeout returns exit 6.
8. A non-timeout required-check failure returns exit 5.

`validate_run()` still operates only on stored files. It does not collect or
compare the current Working Tree, regenerate the Git diff, or rerun checks.
Current S2 collection belongs only to the completion-time Source Binding
boundary. A manifest mismatch is Evidence corruption with exit 8 and does not
repair or roll back files. An S1/S2 identity mismatch is valid Evidence with an
unsatisfied binding and therefore returns exit 9.

Because `harness verify` records check and Source Snapshot results as Evidence,
it returns exit 0 if Evidence recording itself succeeds, even when a required
check fails, times out, or changes product source. S0 or S1 collection failure
does not produce a valid manifest or successful stdout result. A later
`harness complete` expresses refusal through the exit codes above.

Source Binding is a bounded observation. Exit 0 means S2 matched the validated
post-check S1 when `complete` collected it; Harness does not lock the filesystem
or guarantee that source remains unchanged after that observation or after the
command returns.
