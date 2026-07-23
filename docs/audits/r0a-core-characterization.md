# R0a Core Audit and Characterization

Language: English | [한국어](r0a-core-characterization.ko.md)

## Audit baseline

The checkout entered this work on `main` at
`494fe6f25cb4fecd38e71503c38546add5ff5000` with a clean worktree, but the
tracked public `origin/main` was ahead. A clean fast-forward brought the audit
baseline to `b6d0a37c9195f6ef10376b2af9580d12504474e7`; no Core production file
changed across that fast-forward. The worktree was clean again before R0a
files were edited.

The self-hosting Task is `TASK-R0A-CHARACTERIZATION`. Its baseline is
`b6d0a37c9195f6ef10376b2af9580d12504474e7`, its type is `test`, its risk is
`medium`, and its materialized required checks are `contract-sync` and
`unit-test`. `verifier.required` is `false` because this implementation context
cannot also provide an independent fresh-context Manual Verdict.

The audit read both READMEs, architecture and exit-code documents, every ADR,
the repository Harness Skill, package and workflow configuration, all public
Schemas, all production modules, and all tests. `README.ko.md` exists at the
audit baseline. Root `AGENTS.md` did not exist and is added by R0a. Production
code is intentionally unchanged.

Physical lines below count every newline-terminated source line. Logical LOC
is the number of Python AST statements, excluding module, class, and function
docstrings; nested statements and multiple statements on one physical line are
counted separately. This method is reproducible with the Python standard
library and is not a complexity score.

## Current public authority

| Contract | Current authority | Boundary |
| --- | --- | --- |
| Task | `harness.task.create_task()` through `normalize_task_spec()` and `save_task_snapshot()` | Materializes catalog checks, normalizes the Task, records Git HEAD, and stores `.harness/tasks/<TASK_ID>.json` |
| Mechanical Evidence | `harness.evidence.verify_task()` coordinated with `gitdiff.collect_changes()`, `checks.run_checks()`, and `run_manifest.create_run_manifest()` | Produces one saved Run; it does not decide completion |
| Stored Run integrity | `harness.run_validator.validate_run()` | The only public integrity authority for saved mechanical Evidence; byte integrity is delegated to `run_manifest` |
| Verdict structure | `harness.verdict_validator.validate_verdict()` using the packaged `verdict.schema.json` | JSON Schema owns shape and format; expected Task/run IDs are contextual checks |
| Persisted Verdict | `harness.verdict.load_recorded_verdict()` | Revalidates raw and normalized files and requires semantic equality |
| Completion policy | `harness.evidence.complete_task()` | Applies verifier, scope, timeout, and required-check gates only after `validate_run()` |
| Bundle export | `harness.bundle.create_verification_bundle()` | Packages a bounded payload from `ValidatedRun`; it does not rerun the Run |
| CLI exit semantics | `harness.exit_codes.ExitCode` and `harness.cli._exit_code_for()` | Stable public exits are 0 and 2 through 8 |

`show_task()` is retrieval, not full Task authority: it validates the requested
ID and JSON-object readability but does not rerun full Task normalization.

## Command flow and dependency map

```text
__main__ -> cli
cli -> task
cli -> evidence -> checks, gitdiff, run_manifest, run_validator, verdict
cli -> bundle -> run_validator
cli -> verdict -> run_validator, verdict_validator
run_validator -> task, checks (default timeout), run_manifest
```

| Command or operation | Entry point and principal path | Reads | Writes | Canonical validator | Stable handled exits |
| --- | --- | --- | --- | --- | --- |
| `task create` | `cli.main -> create_task -> find_repository_root -> load_check_catalog -> normalize_task_spec -> current_head -> save_task_snapshot` | Input Task JSON, `.harness/checks.json`, Git HEAD | `.harness/tasks/<TASK_ID>.json` | `normalize_task_spec()` | 0, 2, 3 |
| `task show` | `cli.main -> show_task` | Saved Task snapshot | None | `validate_task_id()` plus JSON-object read; no full snapshot normalization | 0, 2, 3 |
| `verify` | `cli.main -> verify_task -> resolve_base_ref -> run_checks -> collect_changes -> Evidence writers -> create_run_manifest` | Saved Task, Git baseline/index/worktree/untracked state, check inputs | Run directory, five core artifacts, check logs, `verification.json`, `run-manifest.json` | Producer path; it does not call `validate_run()` | 0, 2, 3 |
| `validate_run` | Requested identity -> repository and Task lookup -> confined Run reads -> document and cross-document checks -> aggregate recomputation -> manifest validation -> immutable snapshot | Saved Task, required mechanical artifacts, referenced logs, manifest | None | `validate_run()`; raw bytes delegated to `load_and_validate_run_manifest()` | No direct CLI; consumers map identity to 2, repository to 3, corruption to 8 |
| `verifier bundle` | `cli.main -> create_verification_bundle -> validate_run -> gitignore check -> sanitize -> bundle manifest -> atomic rename` | Validated Run, logs, packaged `verifier.md`, Git ignore state | New bundle directory and `manifest.json` | `validate_run()` | 0, 2, 3, 8 |
| `verifier record` | `cli.main -> record_verdict -> validate_run -> read input -> validate_verdict -> atomic writes` | Validated Run, supplied Verdict, packaged Schema | `verdict.raw.json`, `verdict.json` | `validate_run()` and `validate_verdict()` | 0, 2, 3, 8 |
| `verifier show` | `cli.main -> show_verdict -> validate_run -> load_recorded_verdict` | Validated Run, raw and normalized Verdict, packaged Schema | None | `validate_run()`, two Schema validations, equality check | 0, 2, 3, 8 |
| `complete` | `cli.main -> complete_task -> validate_run -> load_recorded_verdict -> policy gates -> atomic completion write` | Validated Run, optional recorded Verdict, packaged severity definitions | `completion.json` on success | `validate_run()` and `load_recorded_verdict()` | 0, 2, 3, 4, 5, 6, 7, 8 |

`verify` returns 0 when it successfully records Evidence, including a required
check failure, timeout, or Scope violation. For an internally valid Run,
completion evaluates verifier exit 7 before scope exit 4, timeout exit 6, and
required-check failure exit 5. Integrity failure exit 8 precedes those policy
decisions. Unexpected uncaught runtime failures may produce process exit 1,
but exit 1 is not a documented Harness contract.

## Production module inventory

The 13 production modules total 4,140 physical lines and 1,960 logical
statements.

### Public symbols and internal imports

| Module | PLOC / LLOC | Public symbols | Production inbound | Internal outbound |
| --- | ---: | --- | --- | --- |
| `harness.__init__` | 3 / 1 | `__version__` | `cli` | None |
| `harness.__main__` | 7 / 3 | None | None | `cli.main` |
| `harness.bundle` | 357 / 156 | bundle schema constant; Bundle errors; `VerificationBundle`; `create_verification_bundle` | `cli` | `exit_codes`, `run_validator`, `task` |
| `harness.checks` | 501 / 239 | timeout constants; `CheckExecutionError`; `run_checks` | `evidence`, `run_validator` | None |
| `harness.cli` | 224 / 85 | `build_parser`, `main` | `__main__` | package version, `bundle`, `evidence`, `exit_codes`, `gitdiff`, `task`, `verdict` |
| `harness.evidence` | 527 / 212 | schema constants; Evidence and Completion errors and records; verify, complete, allocation, atomic-write, and patch helpers | `cli` | `checks`, `exit_codes`, `gitdiff`, `run_manifest`, `run_validator`, `task`, `verdict` |
| `harness.exit_codes` | 23 / 11 | `ExitCode` | `cli`, `evidence`, `bundle` | None |
| `harness.gitdiff` | 508 / 234 | metadata constants; Git errors; change records; `collect_changes`, `resolve_base_ref`, repository and metadata helpers | `cli`, `evidence` | None |
| `harness.run_manifest` | 375 / 191 | manifest constants and error; `RunManifest`; create/load-and-validate functions | `evidence`, `run_validator` | None |
| `harness.run_validator` | 792 / 433 | Run constants and errors; `ValidatedRun`; `validate_run`, `validate_run_id` | `bundle`, `evidence`, `verdict` | `checks`, `run_manifest`, `task` |
| `harness.task` | 414 / 214 | Task constants and errors; create/show/normalize/catalog/save/repository/HEAD/ID helpers | `cli`, `evidence`, `run_validator`, `verdict`, `bundle`, `verdict_validator` | None |
| `harness.verdict` | 279 / 127 | Verdict filenames and errors; `VerdictRecord`; record/show/load/count helpers; duplicate Run ID validator | `cli`, `evidence` | `run_validator`, `task`, `verdict_validator` |
| `harness.verdict_validator` | 130 / 54 | `VerdictValidationError`, `validate_verdict`, `finding_severities` | `verdict` | `task` |

### Responsibility and R0b decision table

| Module | Current responsibility and count | Duplication or drift | Likely extraction candidate | R0b decision |
| --- | --- | --- | --- | --- |
| `__init__` | Package version, 1 | None | None | Keep unchanged |
| `__main__` | Module entry point, 1 | None | None | Keep unchanged |
| `bundle` | Validated-Run consumption, product-change selection, gitignore policy, sanitization, packaged prompt, atomic bundle/manifest, 6 | JSON formatting and safe log reread overlap other consumers | Concrete shared Run-artifact reader only | Keep bundle policy intact; adopt the shared boundary only if extracted |
| `checks` | Check assertion, process and log execution, timeout and tree cleanup, result serialization, 4 | Input checks overlap producer/validator contracts for different trust purposes | None in R0b | Do not split; POSIX/Windows lifecycle is one cohesive responsibility axis |
| `cli` | Parser, dispatch/output JSON, error-to-exit mapping, 3 | None material | None | Keep as a thin adapter |
| `evidence` | Verify orchestration, Run allocation, artifact aggregation, serialization and patch streaming, manifest handoff, completion policy/write, at least 7 | Atomic write duplicated; verification and completion are unrelated phases | Separate mechanical Evidence production from completion policy and record writing | Must change in R0b; first priority |
| `exit_codes` | Stable public exit enum, 1 | None | None | Keep unchanged |
| `gitdiff` | Repository and baseline resolution, four Git layers, raw parsing, binary detection, Scope, metadata exclusion, 7 | Repository lookup and metadata/path policy drift | Canonical Harness metadata/path predicate | Keep live Git collection intact; share only the pure policy |
| `run_manifest` | Expected path normalization, raw-byte records, canonical digest, manifest write and validation, 5 | Strict path/read and atomic write duplicate other modules | Shared strict Run-artifact confinement/read and ordinary atomic bytes | Keep raw-byte digest authority; remove only concrete duplication |
| `run_validator` | Identity, repository/Run lookup, confined reads, document shape, check consistency, scope/metadata recomputation, aggregate result, immutable assembly, at least 7 | Path, metadata, Run ID, JSON-shape helpers are concentrated or copied elsewhere | Internal artifact access, document validators, aggregate validators, immutable assembly behind one façade | Must be decomposed internally in R0b while keeping `validate_run()` as the sole public authority |
| `task` | Task validation, catalog expansion, scope/check normalization, repository/HEAD, snapshot I/O, retrieval, 6 | Repository lookup, JSON read, and force-write semantics differ from peers | Concrete atomic snapshot write and repository policy only after characterization | Keep Task authority; no broad Task rewrite in R0b |
| `verdict` | Validated-Run gate, raw/canonical storage, persisted consistency, identity, finding counts, atomic I/O, 6 | Duplicated Run ID constants/validator and atomic/read helpers | Canonical Run ID plus strict Run-artifact reads | Remove duplication in R0b; keep Verdict persistence responsibility |
| `verdict_validator` | Packaged Schema cache, Schema/context validation, severity extraction, 3 | None; this is already the single Verdict shape authority | None | Keep unchanged |

## Duplication and drift map

| Concern | Current state | R0a finding |
| --- | --- | --- |
| Task identity | `task.validate_task_id()` is reused by other modules | Effectively canonical now |
| Run identity | `run_validator.validate_run_id()` and `verdict.validate_run_id()` duplicate constants and logic with different errors | Remove the Verdict copy and translate the canonical error at the boundary |
| Repository root | Task and Git diff call Git; Run validator scans ancestors for `.git` | Semantics differ for worktrees, fake `.git`, and environment-driven Git; characterize before consolidation |
| Evidence confinement | Run validator and run manifest duplicate safe directory/path/read logic; Verdict reads are weaker; bundle rereads validated logs | Highest-priority concrete shared boundary |
| JSON read/write | Task, Evidence, manifest, Verdict, and bundle have local implementations | Bundle sanitization remains distinct; ordinary atomic JSON is a candidate |
| Atomic write | Evidence, manifest, and Verdict duplicate temp/fsync/replace; Task force writes directly | Share only after preserving failure and replacement behavior |
| Task check normalization | Task producer, check runner assertions, and persisted Run validator all inspect checks | Different trust boundaries; do not collapse into one permissive helper |
| Check consistency | Evidence produces aggregates and Run validator recomputes them | Intentional producer/validator duplication; consumers correctly use validated values |
| Scope consistency | Git diff classifies live changes and Run validator recomputes saved evidence | Intentional trust-boundary duplication; only pure path predicates may be shared |
| Mechanical result | Evidence writes it and Run validator recomputes it | Intentional; bundle, Verdict, and completion do not independently reinterpret it |
| Harness metadata exclusion | Public Git diff policy is copied privately in Run validator | Real drift candidate; make the pure policy canonical |
| Raw-byte digest | Run manifest alone creates and validates the source Evidence digest | Not duplicated; bundle hash is a separate payload contract |
| Verdict validation | Packaged Schema validator owns shape; Verdict module owns persistence equality | Already a sound separation |
| Path normalization | Task/Git producers normalize while persisted Evidence validators reject non-canonical paths | Preserve trust-domain semantics; consolidate only strict Run-artifact handling |

The installed plugin Skill also lags the repository Skill: the installed
v0.1.1 cache requires `.harness/checks.json` before every Core operation,
whereas the repository Skill correctly requires it only for `task create`.
This is adapter preflight drift, not Core behavior, and R0a records it without
changing the plugin cache.

The Task check catalog contains `contract-sync` and `unit-test`; CI additionally
performs installation, diff, wheel, and clean-install smoke checks. Harness
Evidence alone must therefore not be described as the entire CI-equivalent
package validation.

## Existing tests that already protect the contract

| Contract area | Existing coverage retained without duplication |
| --- | --- |
| Passing and failed `ValidatedRun` behavior | `test_validates_passing_optional_failure_without_or_with_verdict`, `test_validates_required_check_failure_and_allows_bundle_and_verdict`, `test_validates_timeout_as_a_failed_but_noncorrupt_run`, `test_validates_scope_violation_as_a_failed_but_noncorrupt_run` |
| Completion policy exits | `test_exit_code_values_are_stable`, scope exit 4, required failure exit 5, timeout exit 6, verifier exit 7, corrupt Evidence exit 8 tests in `test_complete.py` |
| Aggregate and check tampering | `test_rejects_forged_mechanical_and_scope_results`, `test_rejects_inconsistent_check_outcomes` |
| Manifest size, SHA-256, raw-byte, identity, and file-list integrity | `test_detects_raw_byte_tampering_for_every_mechanical_file`, `test_rejects_manifest_identity_hash_and_structure_tampering`, `test_rejects_missing_files_and_unsafe_manifest_records` |
| Task/run identity and snapshot equality | `test_rejects_identity_and_task_snapshot_mismatches` plus consumer mismatch tests |
| Traversal, POSIX absolute, duplicate, missing, and file-symlink paths | `test_rejects_unsafe_duplicate_and_missing_evidence_paths`, `test_rejects_evidence_symlink_escape` |
| Failed-Run bundle and canonical consumer boundary | `test_validates_required_check_failure_and_allows_bundle_and_verdict`, `test_all_consumers_reject_the_same_corrupt_run`, `test_consumers_use_validated_digest_and_do_not_recover_mismatches` |
| Verdict raw/snapshot and identity | raw and normalized tampering tests, `test_record_rejects_task_run_mismatch`, runtime expected-identity tests |
| Optional fail, unable, and blocker Verdicts | `test_optional_verifier_blocker_rejects_completion`, `test_fail_and_unable_verdicts_reject_completion` |
| Explicit Run ID and no latest selection | `test_invalid_run_id_and_missing_run_id_return_invalid_input_exit_code` |
| Public package resources and contract sync | `VerdictContractCoherenceTests`, CLI/package-resource tests, and `scripts/sync_contracts.py --check` |
| Bilingual public documentation | `tests/test_docs.py` enforces one pair, reciprocal selectors, local links, and same-language navigation |

`tests/test_codex_permissions.py` protects a separate Codex credential profile.
It is outside the Core characterization dependency cone and is preserved, not
reimplemented.

## New Characterization Tests

R0a adds only gaps not already covered:

- explicit `ValidatedRun` type assertions for passing, required-failure,
  timeout, and Scope-violation Runs;
- a POSIX Evidence Run directory symlink escape that moves the Run outside the
  repository and replaces the logical Run directory with a symlink;
- a Windows drive-form `C:/...` Evidence path rejection case;
- a CLI test proving that `verify` returns exit 0 after successfully recording
  a required-check failure while the stored mechanical result is `fail`.

These tests change no production behavior.

## Known-gap executable tests

Two ordinary-discovery tests are marked `unittest.expectedFailure` because the
limitations are present at this baseline:

1. `test_complete_rejects_product_source_changes_after_verification` expresses
   the desired rule that completion reject a source change made after verify.
   It currently fails because completion reads only saved Evidence and writes
   `completion.json` successfully.
2. `test_verify_cannot_override_task_baseline_to_hide_product_changes` creates
   a post-Task commit outside Scope and verifies with `--base-ref HEAD`. It
   currently fails because the Run records the later HEAD as baseline and
   omits the post-Task change.

When source binding and the baseline rule are implemented, R1b must remove the
decorators. A rejection of `--base-ref`, or recording the original Task
baseline and visible change, makes the second test an unexpected success and
therefore fails the suite until the decorator is removed.

## Known contract

- `validate_run()` validates internal integrity of stored Evidence.
- A failed required check, timeout, Scope violation, or mechanical fail is not
  corrupted Evidence when all stored records agree.
- Such a Run is a `ValidatedRun` and may be bundled or receive a Manual Verdict.
- Completion policy separately rejects Scope, timeout, and required-check
  failures with stable exits 4, 6, and 5.
- A bundle does not rerun checks or recollect Git state.
- Bundle, completion, and Verdict consumers first pass through `validate_run()`.
- A recorded optional-verifier `fail`, `unable`, or blocker is not ignored.
- `complete --run-id` requires an explicit Run; implicit latest selection does
  not exist.
- Current Working Tree or current-source binding is not provided.
- `--base-ref` remains a published v0.1.1 limitation.
- The Run manifest is a local consistency identifier, not a signature,
  attestation, immutable ledger, or external trust anchor.

## Refactoring boundary for R0b

### Responsibilities that must be separated

1. Separate mechanical Evidence production from completion policy and
   completion-record writing inside `evidence.py`.
2. Keep `validate_run(task_id, run_id, cwd=...)` as the sole public façade while
   separating its internal responsibilities for safe artifact access,
   per-document validation, cross-document check/scope/result consistency, and
   immutable `ValidatedRun` assembly.
3. Establish one concrete strict Run-artifact confinement/read boundary for
   validator, manifest, Verdict persistence, and bundle consumption. This is
   not a generic repository or service abstraction.
4. Canonicalize Run ID validation and the pure Harness metadata/path-boundary
   policy inside the dependency cone.

### Responsibilities that must remain

- the public `validate_run()` signature, `ValidatedRun`, and error-to-exit
  semantics;
- Task/check normalization in `task`;
- live Git collection in `gitdiff` and process lifecycle in `checks`;
- raw-byte Evidence digest authority in `run_manifest`;
- packaged Verdict Schema authority in `verdict_validator`;
- bundle portability and completion policy as consumers of `ValidatedRun`;
- current CLI JSON, artifact filenames, Schema versions, and stable exit codes.

### Duplication to remove in the R0b dependency cone

- Verdict's separate Run ID constants and validator;
- copied strict Evidence path and read logic between validator and manifest;
- copied Harness metadata constants and component-boundary predicate;
- ordinary atomic JSON/bytes writers only where their current semantics are
  characterized and equivalent.

### Intentionally untouched structural issues

- Source Snapshot and current-source binding;
- removal or semantic change of `--base-ref`;
- Task, Evidence, Verdict, Bundle Schema or exit-code changes;
- check execution and Windows Job/process-tree behavior;
- bundle size limits and comprehensive secret redaction;
- external verifier, LLM, credential, retry, or provider adapters;
- ledger, hooks, approval state, runtime monitoring, or Agent topology;
- a generic repository, service layer, registry, or placeholder module;
- mechanical splitting of `checks.py` or `gitdiff.py` for line-count reduction.

## Recorded risks outside this Phase

- Bundle log copying rereads a validated path, leaving a check-to-copy TOCTOU
  window for concurrent replacement.
- Persisted Verdict reads do not use the strict Run confinement helper, so a
  later symlink can point at an external but valid Verdict document.
- The saved Task snapshot itself is read without symlink confinement.
- Three repository-root implementations have different Git/worktree semantics.
- `show_task()` does not fully revalidate the stored snapshot or compare the
  document's ID beyond the requested path.
- Task `--force` writes directly rather than using the atomic replacement
  pattern used by Evidence and Verdict files.
- `validate_run()` validates the Task fields needed for Run integrity, not the
  entire original Task contract.
- CI is Ubuntu/Python 3.11 only; it does not directly exercise every claimed
  platform or every Python version above 3.11.

These are audit findings, not authorization to change behavior in R0a.

## Validation recorded during R0a

| Command or check | Actual result |
| --- | --- |
| `.release-venv/bin/python -m pip install -e '.[test]'` | First sandboxed attempt exit 1 because PyPI DNS was unavailable; approved retry exit 0 and installed editable `outcome-harness 0.1.1` |
| `.release-venv/bin/python scripts/sync_contracts.py --check` | Exit 0 |
| Targeted docs, Run-integrity, and completion suite | 40 tests, exit 0, expected failures 2 |
| `PYTHONPATH=src .release-venv/bin/python -m unittest discover -s tests -v` | 143 tests, exit 0, skips 3, expected failures 2 |
| `git diff --check` | Exit 0 |
| `git diff --check HEAD^ HEAD` | Exit 0 |
| `.release-venv/bin/python -m build --wheel --outdir <TEMP>` | First isolated-build attempt exit 1 because PyPI DNS was unavailable; approved retry exit 0 and built `outcome_harness-0.1.1-py3-none-any.whl` |
| Create a new clean venv with `.release-venv/bin/python -m venv` | Exit 0 |
| Install the built wheel in the clean venv | First sandboxed attempt exit 1 because dependencies could not resolve through PyPI; approved retry exit 0 |
| Installed `harness --help` | Exit 0 |
| Installed `harness --version` | Exit 0, `harness 0.1.1` |
| Installed `import harness`, `validate_run`, and `validate_verdict` | Exit 0 |
| Load and parse packaged `verdict.schema.json` and read packaged `verifier.md` | Exit 0 |

The three skips are two macOS filesystem cases for non-UTF-8 byte filenames
and one nested Codex sandbox smoke that the current process cannot start. The
two expected failures are the executable source-binding and `--base-ref` gaps
described above. No Windows E2E was run on this macOS host.
