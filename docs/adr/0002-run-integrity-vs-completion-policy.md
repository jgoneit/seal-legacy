# ADR 0002: Separate Run Integrity from Completion Policy

## Status

Accepted

## Context

Earlier completion and verifier-bundle operations each reread saved Task and Run Evidence and independently checked some consistency properties. Under that structure, different commands could interpret the same Run differently, and the places to update validation of check results, scope results, and Evidence paths were scattered.

A failed work result and damaged Evidence are also distinct states. Even when a required check fails, a timeout occurs, or a Scope violation is recorded, the Run may still be valid Evidence that accurately preserves the result at that time. Conversely, if internal data contradicts itself—for example, `passed=true` with a non-zero exit code—the Run cannot be trusted before completion policy is even considered.

## Decision

- Make `harness.run_validator.validate_run(task_id, run_id, cwd=...)` the canonical entry point for stored Run integrity.
- The validator checks the existence, readability, identity, and mutual consistency of the saved Task snapshot, the Run's `task.json`, `changed-files.json`, `diff.patch`, `checks.json`, `verification.json`, and check logs, then returns an immutable `ValidatedRun`.
- The validator rejects Evidence path traversal, absolute paths, duplicate paths, and symlink escapes outside the Run directory.
- The validator does not treat a failed check, timeout, Scope violation, or `mechanical_result="fail"` as corruption. A failed Run is still a `ValidatedRun` when its structure is consistent.
- `ValidatedRun.read_log_bytes(relative_path)` is the narrow consumer boundary for check-log bytes. It accepts only a `PurePosixPath` present in that instance's `log_paths`, returns raw bytes, rejects a symlinked Evidence-directory chain at access time, and reapplies the confined Run-artifact read. Consumers such as Bundle do not import the internal artifact reader.
- `evidence.complete_task`, `bundle.create_verification_bundle`, `verdict.record_verdict`, and `verdict.show_verdict` use the same `ValidatedRun` before applying their respective policies.
- Completion separately evaluates current-source binding, Scope, required checks, timeouts, Manual Verdicts, and blocker conditions. Bundles handle only portability and output safety, while Verdict paths handle only the Manual Verdict contract and raw/snapshot preservation.
- The validator does not recollect Git diffs, rerun checks, compare current source, call model APIs or external CLIs, or operate Agent runtime hooks, approvals, or state machines.

## Consequences

When stored Evidence is damaged, every consumer rejects it at the same canonical error boundary. Conversely, a mechanically failed Run is preserved as input to an external review bundle and an independent Manual Verdict. The original v0.2 consumer commands and existing exit-code numbers do not change; only `complete` expresses completion policy for a valid Run through exits 4–7 and 9.

The log accessor does not rerun `validate_run()`, recompute the Run Manifest, or make local files immutable. A log that has become missing, unreadable, non-regular, or an external symlink escape after validation raises `RunEvidenceError`; the checks are best-effort access-time confinement, not a filesystem lock or a race-free descriptor protocol. Other same-user filesystem mutation remains within the local-storage limitations below.

This decision does not make the local filesystem immutable storage. ADR 0003 subsequently adds a mechanical Evidence manifest and digest to detect modified or missing files, but it still does not address attacks in which the same local user recomputes both Evidence and its manifest, semantic binding between the diff and changed files, or binding between the source at verification time and the current source.

## Rejected alternatives

- Have completion, bundle, and Verdict paths each recheck Evidence consistency independently
- Treat mechanical failure immediately as corrupt Evidence
- Regenerate Git diffs or rerun checks in the validator
- Add source snapshots, an external verifier adapter, and automatic repair to the validator at the same time

## Source-binding amendment

[ADR 0005](0005-verify-complete-source-binding.md) extends this boundary with
versioned persisted S0/S1 validation while keeping `validate_run()` limited to
stored Evidence. Current-source S2 collection remains a separate completion-time
policy step.

## Read-only Run Summary amendment

Core `0.3.0.dev0` adds
`harness run show <TASK_ID> --run-id <RUN_ID>` as a separate read-only consumer
of this authority. The command calls `validate_run()` once and projects only
the returned immutable `ValidatedRun` into the transient
`validated-run-summary/v1` stdout envelope. It does not add a persisted
artifact or Evidence schema, and it does not inspect `verification.json`
through another interpretation path.

A valid failed Run returns exit 0 with its check, timeout, Scope, and S0/S1
state represented in the envelope. Missing, corrupt, contradictory,
unsupported, or unsafe Evidence returns exit 8 and no envelope. Invalid
identity remains exit 2 and repository failure remains exit 3. Because the
command exposes stored state rather than applying completion policy, it does
not use exits 4–7 or 9 for valid Runs.

Extending `verify` stdout was rejected because its exact identity-only JSON is
already public and `verify` is a write transition. A Python-only API was
rejected because subprocess adapters do not import Core. Direct raw Evidence
interpretation was rejected because it would create a second stored-Run
authority. Latest-Run selection, S2 collection, Verdict or completion lookup,
reviewer invocation, retry, repair, and next-action advice remain outside this
consumer.
