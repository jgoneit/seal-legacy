# Harness exit codes

Language: English | [한국어](exit-codes.ko.md)

The exit codes below are part of the public CLI contract. New commands may be added later, but the meanings of already defined numbers will not change.

| Code | Meaning | Typical condition |
| ---: | --- | --- |
| 0 | success | The requested command completed successfully and, for `complete`, all completion conditions were satisfied |
| 2 | invalid input or schema | Invalid CLI arguments, Task/run mismatch, or an invalid Task Spec or saved Task structure |
| 3 | git/repository error | Git execution failure, execution outside a Git repository, or an unresolvable Git baseline |
| 4 | scope violation | The stored Evidence records a change outside the product Scope |
| 5 | required check failure | A non-timeout required check failure is stored |
| 6 | timeout | A required check timeout is stored |
| 7 | verifier gate not satisfied | Required verifier Evidence is missing, or the recorded Verdict is fail/unable or contains a blocker |
| 8 | evidence missing or corrupt | Required Evidence files are missing, JSON is unreadable, or stored records contradict one another |

## `harness complete` decision process

`harness complete <TASK_ID> --run-id <RUN_ID>` reads only the Evidence in the specified Run directory and does not rerun checks or regenerate the Git diff. First, the canonical `validate_run()` checks the stored Task/Run identity, artifact paths, check results, scope, mechanical result, and raw-byte digest integrity in `run-manifest.json`. `--run-id` is required; implicit latest-Run selection is not supported.

All of the following must be true for success (exit 0):

- The requested Task and Run ID match the identity in the saved Task and `verification.json`.
- The required Evidence files and the Evidence files listed in `verification.json` exist, and JSON Evidence passes parsing and internal consistency checks.
- `run-manifest.json` matches the expected mechanical file list exactly, and each file's raw-byte size and SHA-256 and the canonical `evidence_sha256` match.
- `scope_pass` is `true`.
- Every required check has `passed=true` and none timed out.
- `required_checks_pass=true` and `mechanical_result="pass"`.
- If the Task has `verifier.required` set to `true`, a valid Manual Verdict exists, the Verdict is `pass`, and it has zero blockers.
- If the Task has `verifier.required` set to `false`, the Task can complete mechanically without a Verdict. However, exit 7 is returned if a recorded Verdict is `fail` or `unable` or contains a blocker.

A required check failure, timeout, Scope violation, or `mechanical_result="fail"` is not itself an error from `validate_run()`. These are validly recorded failed Runs that can still be exported as bundles or have Manual Verdicts recorded. Only `complete` rejects them with exit 4, 5, 6, or 7 according to completion policy.

When a Verdict has been recorded, the raw Verdict and normalized snapshot must both exist, parse successfully, and match. If only one is present or either is corrupt, completion returns exit 8 even when the verifier is optional. If neither exists and the verifier is optional, mechanical-only completion remains allowed. Warning and note findings do not block `complete`; their counts are recorded in `completion.json`. A successful completion also records the `evidence_sha256` of the consumed mechanical Evidence set.

After the stored Evidence has been read successfully, the verifier gate (exit 7) is evaluated first, followed by scope (exit 4), required timeout (exit 6), and required check failure (exit 5). Missing or corrupt Evidence (exit 8) is reported before these completion decisions.

`validate_run()` operates only on stored files. It does not collect or compare the current working tree, regenerate the Git diff, or rerun checks. A manifest mismatch is treated as Evidence corruption with exit 8 and does not repair or roll back files. Current source binding is therefore not part of this exit-code contract.

Because `harness verify` records check results as Evidence, it returns exit 0 if Evidence recording itself succeeds, even when a required check fails or times out. A later `harness complete` expresses the refusal to complete through the exit codes above.
