# ADR 0002: Separate Run Integrity from Completion Policy

Language: English | [한국어](0002-run-integrity-vs-completion-policy.ko.md)

## Status

Accepted

## Context

In Phase 1, completion and verifier-bundle operations each reread saved Task and Run Evidence and independently checked some consistency properties. Under that structure, different commands could interpret the same Run differently, and the places to update validation of check results, scope results, and Evidence paths were scattered.

A failed work result and damaged Evidence are also distinct states. Even when a required check fails, a timeout occurs, or a Scope violation is recorded, the Run may still be valid Evidence that accurately preserves the result at that time. Conversely, if internal data contradicts itself—for example, `passed=true` with a non-zero exit code—the Run cannot be trusted before completion policy is even considered.

## Decision

- Make `harness.run_validator.validate_run(task_id, run_id, cwd=...)` the canonical entry point for stored Run integrity.
- The validator checks the existence, readability, identity, and mutual consistency of the saved Task snapshot, the Run's `task.json`, `changed-files.json`, `diff.patch`, `checks.json`, `verification.json`, and check logs, then returns an immutable `ValidatedRun`.
- The validator rejects Evidence path traversal, absolute paths, duplicate paths, and symlink escapes outside the Run directory.
- The validator does not treat a failed check, timeout, Scope violation, or `mechanical_result="fail"` as corruption. A failed Run is still a `ValidatedRun` when its structure is consistent.
- `evidence.complete_task`, `bundle.create_verification_bundle`, `verdict.record_verdict`, and `verdict.show_verdict` use the same `ValidatedRun` before applying their respective policies.
- Completion additionally evaluates only Scope, required checks, timeouts, Manual Verdicts, and blocker conditions. Bundles handle only portability and output safety, while Verdict paths handle only the Manual Verdict contract and raw/snapshot preservation.
- The validator does not recollect Git diffs, rerun checks, compare current source, call model APIs or external CLIs, or operate Agent runtime hooks, approvals, or state machines.

## Consequences

When stored Evidence is damaged, every consumer rejects it at the same canonical error boundary. Conversely, a mechanically failed Run is preserved as input to an external review bundle and an independent Manual Verdict. Public CLI commands and existing exit-code numbers do not change; only `complete` expresses completion policy for a valid Run through exits 4–7.

This decision does not make the local filesystem immutable storage. ADR 0003 subsequently adds a mechanical Evidence manifest and digest to detect modified or missing files, but it still does not address attacks in which the same local user recomputes both Evidence and its manifest, semantic binding between the diff and changed files, or binding between the source at verification time and the current source.

## Rejected alternatives

- Have completion, bundle, and Verdict paths each recheck Evidence consistency independently
- Treat mechanical failure immediately as corrupt Evidence
- Regenerate Git diffs or rerun checks in the validator
- Add source snapshots, an external verifier adapter, and automatic repair to the validator at the same time
