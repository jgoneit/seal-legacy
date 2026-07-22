# R0a Core 감사와 Characterization

Language: [English](r0a-core-characterization.md) | 한국어

## 감사 기준

작업 시작 시 checkout은 깨끗한 `main`, HEAD
`494fe6f25cb4fecd38e71503c38546add5ff5000`이었지만 추적 중인 공개
`origin/main`보다 뒤에 있었다. 깨끗한 fast-forward 후 감사 기준은
`b6d0a37c9195f6ef10376b2af9580d12504474e7`이 됐으며, 그 구간에서 Core
production 파일은 바뀌지 않았다. R0a 파일을 수정하기 직전 worktree도 다시
깨끗한 상태였다.

Self-hosting Task는 `TASK-R0A-CHARACTERIZATION`이다. baseline은
`b6d0a37c9195f6ef10376b2af9580d12504474e7`, type은 `test`, risk는
`medium`이며 materialize된 required check는 `contract-sync`, `unit-test`다.
같은 구현 context가 독립된 fresh-context Manual Verdict를 제공할 수 없으므로
`verifier.required`는 `false`다.

감사에서는 두 README, architecture와 exit-code 문서, 모든 ADR, 저장소 Harness
Skill, package와 workflow 설정, 모든 공개 Schema, 모든 production module과 모든
test를 읽었다. 감사 baseline에는 `README.ko.md`가 존재한다. 루트 `AGENTS.md`는
없어서 R0a에서 추가한다. Production code는 의도적으로 수정하지 않는다.

아래 physical line은 newline으로 끝나는 모든 source line을 센 값이다. Logical LOC는
Python AST statement 수에서 module, class, function docstring을 뺀 값이다. 중첩된
statement와 한 physical line 안의 복수 statement는 각각 센다. Python 표준 라이브러리로
재현할 수 있는 수치이며 complexity 점수는 아니다.

## 현재 public authority

| 계약 | 현재 authority | 경계 |
| --- | --- | --- |
| Task | `harness.task.create_task()`에서 `normalize_task_spec()`과 `save_task_snapshot()`으로 이어지는 경로 | Catalog check를 materialize하고 Task를 정규화하며 Git HEAD와 `.harness/tasks/<TASK_ID>.json` snapshot을 저장한다 |
| Mechanical Evidence | `harness.evidence.verify_task()`와 `gitdiff.collect_changes()`, `checks.run_checks()`, `run_manifest.create_run_manifest()` | 저장 Run 하나를 생성하며 completion을 판정하지 않는다 |
| 저장 Run integrity | `harness.run_validator.validate_run()` | 저장 mechanical Evidence의 유일한 public integrity authority이며 raw-byte 검사는 `run_manifest`에 위임한다 |
| Verdict 구조 | packaged `verdict.schema.json`을 사용하는 `harness.verdict_validator.validate_verdict()` | JSON Schema가 shape과 format을 결정하고 expected Task/run ID만 context로 검사한다 |
| 저장 Verdict | `harness.verdict.load_recorded_verdict()` | raw와 normalized 파일을 각각 재검증하고 의미적 equality를 요구한다 |
| Completion policy | `harness.evidence.complete_task()` | `validate_run()` 이후 verifier, scope, timeout, required-check gate만 적용한다 |
| Bundle export | `harness.bundle.create_verification_bundle()` | `ValidatedRun`에서 제한된 payload를 만들며 Run을 재실행하지 않는다 |
| CLI exit 의미 | `harness.exit_codes.ExitCode`와 `harness.cli._exit_code_for()` | Stable public exit는 0과 2부터 8이다 |

`show_task()`는 retrieval이지 전체 Task authority가 아니다. 요청 ID와 JSON object로
읽을 수 있는지는 검사하지만 전체 Task normalization을 다시 실행하지 않는다.

## Command 흐름과 dependency 지도

```text
__main__ -> cli
cli -> task
cli -> evidence -> checks, gitdiff, run_manifest, run_validator, verdict
cli -> bundle -> run_validator
cli -> verdict -> run_validator, verdict_validator
run_validator -> task, checks (default timeout), run_manifest
```

| Command 또는 operation | Entry point와 주요 경로 | 읽는 자료 | 쓰는 자료 | Canonical validator | Stable handled exit |
| --- | --- | --- | --- | --- | --- |
| `task create` | `cli.main -> create_task -> find_repository_root -> load_check_catalog -> normalize_task_spec -> current_head -> save_task_snapshot` | 입력 Task JSON, `.harness/checks.json`, Git HEAD | `.harness/tasks/<TASK_ID>.json` | `normalize_task_spec()` | 0, 2, 3 |
| `task show` | `cli.main -> show_task` | 저장 Task snapshot | 없음 | `validate_task_id()`와 JSON object read, 전체 snapshot normalization 없음 | 0, 2, 3 |
| `verify` | `cli.main -> verify_task -> resolve_base_ref -> run_checks -> collect_changes -> Evidence writer -> create_run_manifest` | 저장 Task, Git baseline/index/worktree/untracked state, check 입력 | Run directory, core artifact, check log, `verification.json`, `run-manifest.json` | Producer 경로이며 `validate_run()`은 호출하지 않음 | 0, 2, 3 |
| `validate_run` | 요청 identity -> repository와 Task 탐색 -> confined Run read -> document와 cross-document 검사 -> aggregate 재계산 -> manifest 검증 -> immutable snapshot | 저장 Task, required mechanical artifact, 참조 log, manifest | 없음 | `validate_run()`이며 raw byte는 `load_and_validate_run_manifest()`에 위임 | 직접 CLI 없음. Consumer가 identity를 2, repository를 3, corruption을 8로 변환 |
| `verifier bundle` | `cli.main -> create_verification_bundle -> validate_run -> gitignore 검사 -> sanitize -> bundle manifest -> atomic rename` | Validated Run, log, packaged `verifier.md`, Git ignore state | 새 bundle directory와 `manifest.json` | `validate_run()` | 0, 2, 3, 8 |
| `verifier record` | `cli.main -> record_verdict -> validate_run -> 입력 read -> validate_verdict -> atomic write` | Validated Run, 제공 Verdict, packaged Schema | `verdict.raw.json`, `verdict.json` | `validate_run()`과 `validate_verdict()` | 0, 2, 3, 8 |
| `verifier show` | `cli.main -> show_verdict -> validate_run -> load_recorded_verdict` | Validated Run, raw와 normalized Verdict, packaged Schema | 없음 | `validate_run()`, Schema 검증 두 번, equality | 0, 2, 3, 8 |
| `complete` | `cli.main -> complete_task -> validate_run -> load_recorded_verdict -> policy gate -> atomic completion write` | Validated Run, optional 저장 Verdict, packaged severity 정의 | 성공 시 `completion.json` | `validate_run()`과 `load_recorded_verdict()` | 0, 2, 3, 4, 5, 6, 7, 8 |

`verify`는 required check failure, timeout, Scope violation이라도 Evidence 저장에
성공하면 exit 0을 반환한다. 내부적으로 유효한 Run의 completion은 verifier exit 7,
scope exit 4, timeout exit 6, required-check failure exit 5 순서로 판정한다. Integrity
failure exit 8은 이 policy보다 먼저 처리된다. 예상하지 못한 uncaught runtime failure는
process exit 1을 만들 수 있지만 exit 1은 문서화된 Harness 계약이 아니다.

## Production module inventory

13개 production module은 전체 4,140 physical line과 1,960 logical statement다.

### Public symbol과 내부 import

| Module | PLOC / LLOC | Public symbol | Production inbound | Internal outbound |
| --- | ---: | --- | --- | --- |
| `harness.__init__` | 3 / 1 | `__version__` | `cli` | 없음 |
| `harness.__main__` | 7 / 3 | 없음 | 없음 | `cli.main` |
| `harness.bundle` | 357 / 156 | bundle schema 상수, Bundle error, `VerificationBundle`, `create_verification_bundle` | `cli` | `exit_codes`, `run_validator`, `task` |
| `harness.checks` | 501 / 239 | timeout 상수, `CheckExecutionError`, `run_checks` | `evidence`, `run_validator` | 없음 |
| `harness.cli` | 224 / 85 | `build_parser`, `main` | `__main__` | package version, `bundle`, `evidence`, `exit_codes`, `gitdiff`, `task`, `verdict` |
| `harness.evidence` | 527 / 212 | schema 상수, Evidence와 Completion error/record, verify, complete, allocation, atomic-write, patch helper | `cli` | `checks`, `exit_codes`, `gitdiff`, `run_manifest`, `run_validator`, `task`, `verdict` |
| `harness.exit_codes` | 23 / 11 | `ExitCode` | `cli`, `evidence`, `bundle` | 없음 |
| `harness.gitdiff` | 508 / 234 | metadata 상수, Git error, change record, `collect_changes`, `resolve_base_ref`, repository와 metadata helper | `cli`, `evidence` | 없음 |
| `harness.run_manifest` | 375 / 191 | manifest 상수와 error, `RunManifest`, create/load-and-validate 함수 | `evidence`, `run_validator` | 없음 |
| `harness.run_validator` | 792 / 433 | Run 상수와 error, `ValidatedRun`, `validate_run`, `validate_run_id` | `bundle`, `evidence`, `verdict` | `checks`, `run_manifest`, `task` |
| `harness.task` | 414 / 214 | Task 상수와 error, create/show/normalize/catalog/save/repository/HEAD/ID helper | `cli`, `evidence`, `run_validator`, `verdict`, `bundle`, `verdict_validator` | 없음 |
| `harness.verdict` | 279 / 127 | Verdict filename과 error, `VerdictRecord`, record/show/load/count helper, 중복 Run ID validator | `cli`, `evidence` | `run_validator`, `task`, `verdict_validator` |
| `harness.verdict_validator` | 130 / 54 | `VerdictValidationError`, `validate_verdict`, `finding_severities` | `verdict` | `task` |

### 책임과 R0b 판단

| Module | 현재 책임과 개수 | 중복 또는 drift | 분리 후보 | R0b 판단 |
| --- | --- | --- | --- | --- |
| `__init__` | Package version, 1 | 없음 | 없음 | 유지 |
| `__main__` | Module entry point, 1 | 없음 | 없음 | 유지 |
| `bundle` | Validated Run 소비, product change 선택, gitignore policy, sanitization, packaged prompt, atomic bundle/manifest, 6 | JSON formatting과 safe log reread가 다른 consumer와 겹침 | 구체적인 공용 Run-artifact reader만 | Bundle policy는 유지하고 공용 경계가 분리되면 그것만 사용 |
| `checks` | Check assertion, process와 log 실행, timeout과 process-tree cleanup, result serialization, 4 | 입력 check를 producer/validator도 다른 목적으로 검사함 | R0b 대상 없음 | POSIX/Windows lifecycle은 한 책임 축이므로 분할하지 않음 |
| `cli` | Parser, dispatch/output JSON, error-to-exit mapping, 3 | 실질적 중복 없음 | 없음 | 얇은 adapter로 유지 |
| `evidence` | Verify orchestration, Run allocation, artifact aggregation, serialization과 patch streaming, manifest handoff, completion policy/write, 최소 7 | Atomic write 중복, verification과 completion의 서로 다른 phase가 공존 | Mechanical Evidence 생성과 completion policy/write 분리 | R0b에서 반드시 수정할 1순위 |
| `exit_codes` | Stable public exit enum, 1 | 없음 | 없음 | 유지 |
| `gitdiff` | Repository와 baseline, 네 Git layer, raw parsing, binary 판정, Scope, metadata 제외, 7 | Repository 탐색과 metadata/path policy drift | Canonical Harness metadata/path predicate | Live Git 수집은 유지하고 순수 policy만 공유 |
| `run_manifest` | Expected path 정규화, raw-byte record, canonical digest, manifest write와 validation, 5 | Strict path/read와 atomic write가 다른 module과 중복 | 공용 strict Run-artifact confinement/read와 ordinary atomic bytes | Raw-byte digest authority는 유지하고 구체적 중복만 제거 |
| `run_validator` | Identity, repository/Run 탐색, confined read, document shape, check consistency, scope/metadata 재계산, aggregate result, immutable assembly, 최소 7 | Path, metadata, Run ID, JSON-shape helper가 집중되거나 외부에 복제됨 | 단일 façade 뒤의 artifact access, document validator, aggregate validator, immutable assembly | `validate_run()` public authority를 유지하면서 R0b에서 내부 분리 |
| `task` | Task validation, catalog expansion, scope/check normalization, repository/HEAD, snapshot I/O, retrieval, 6 | Repository 탐색, JSON read, force-write 의미가 다른 module과 다름 | Characterization 후 구체적 atomic snapshot write와 repository policy | Task authority 유지, R0b에서 전면 rewrite 금지 |
| `verdict` | Validated Run gate, raw/canonical 저장, 저장 consistency, identity, finding count, atomic I/O, 6 | Run ID 상수/validator와 atomic/read helper 중복 | Canonical Run ID와 strict Run-artifact read | R0b에서 중복 제거, Verdict persistence 책임 유지 |
| `verdict_validator` | Packaged Schema cache, Schema/context validation, severity 추출, 3 | 없음, 이미 Verdict shape 단일 authority | 없음 | 유지 |

## 중복과 drift 지도

| 관심사 | 현재 상태 | R0a 판단 |
| --- | --- | --- |
| Task identity | 다른 module이 `task.validate_task_id()`를 재사용 | 사실상 canonical |
| Run identity | `run_validator.validate_run_id()`와 `verdict.validate_run_id()`가 상수와 로직을 중복하며 error type만 다름 | Verdict 복제를 제거하고 경계에서 canonical error를 번역 |
| Repository root | Task와 Git diff는 Git을 호출하고 Run validator는 `.git` ancestor를 탐색 | Worktree, 가짜 `.git`, Git environment 의미가 다르므로 통합 전 characterization 필요 |
| Evidence confinement | Run validator와 manifest가 safe directory/path/read를 중복하고 Verdict read는 더 약하며 bundle은 validated log를 재읽음 | 가장 우선할 구체적 공용 경계 |
| JSON read/write | Task, Evidence, manifest, Verdict, bundle이 각자 구현 | Bundle sanitization은 별도 유지, ordinary atomic JSON은 후보 |
| Atomic write | Evidence, manifest, Verdict가 temp/fsync/replace를 중복하고 Task force는 직접 write | Failure와 replacement 의미를 보호한 뒤에만 공유 |
| Task check normalization | Task producer, check runner assertion, 저장 Run validator가 모두 check를 검사 | Trust boundary가 다르므로 하나의 permissive helper로 합치지 않음 |
| Check consistency | Evidence가 aggregate를 생성하고 Run validator가 재계산 | 의도적인 producer/validator 이중 계산, consumer는 validated 값만 사용 |
| Scope consistency | Git diff가 live change를 분류하고 Run validator가 저장 Evidence에서 재계산 | 의도적인 trust-boundary 이중 계산, 순수 path predicate만 공유 가능 |
| Mechanical result | Evidence가 저장하고 Run validator가 재계산 | 의도적이며 bundle, Verdict, completion은 별도 재해석하지 않음 |
| Harness metadata 제외 | Git diff의 public policy가 Run validator에 private 복사됨 | 실제 drift 후보, 순수 policy를 canonical하게 만들 대상 |
| Raw-byte digest | Run manifest만 source Evidence digest를 생성하고 검증 | 중복 아님, bundle hash는 다른 payload 계약 |
| Verdict validation | Packaged Schema validator가 shape, Verdict module이 persistence equality를 소유 | 이미 적절한 분리 |
| Path normalization | Task/Git producer는 정규화하고 저장 Evidence validator는 non-canonical path를 거부 | Trust-domain 의미를 유지하고 strict Run artifact만 통합 |

설치된 plugin Skill과 저장소 Skill에도 drift가 있다. 설치된 v0.1.1 cache는 모든 Core
operation 전에 `.harness/checks.json`을 요구하지만 저장소 Skill은 `task create`에만
요구한다. 이는 Core behavior가 아닌 adapter preflight drift이므로 R0a에서는 기록만 하고
plugin cache를 수정하지 않는다.

Task check catalog에는 `contract-sync`와 `unit-test`만 있다. CI는 설치, diff, wheel,
clean-install smoke를 추가로 수행한다. 따라서 Harness Evidence만으로 CI-equivalent package
검증 전체를 완료했다고 주장하면 안 된다.

## 기존 테스트가 이미 보호하는 계약

| 계약 영역 | 중복 추가 없이 유지한 기존 coverage |
| --- | --- |
| Passing/failed `ValidatedRun` | `test_validates_passing_optional_failure_without_or_with_verdict`, required failure, timeout, Scope violation의 noncorrupt Run test |
| Completion policy exit | `test_exit_code_values_are_stable`과 `test_complete.py`의 scope 4, failure 5, timeout 6, verifier 7, corrupt Evidence 8 test |
| Aggregate/check tampering | `test_rejects_forged_mechanical_and_scope_results`, `test_rejects_inconsistent_check_outcomes` |
| Manifest size, SHA-256, raw-byte, identity, file list | raw-byte tampering, manifest identity/hash/structure, missing/unsafe record test |
| Task/run identity와 snapshot equality | `test_rejects_identity_and_task_snapshot_mismatches`와 consumer mismatch test |
| Traversal, POSIX absolute, duplicate, missing, file symlink | unsafe/duplicate/missing path test와 `test_rejects_evidence_symlink_escape` |
| Failed Run bundle과 canonical consumer boundary | required-failure bundle/Verdict test, all-consumer corruption test, validated digest consumer test |
| Verdict raw/snapshot과 identity | raw/normalized tampering, record mismatch, runtime expected-identity test |
| Optional fail/unable/blocker | optional blocker와 fail/unable completion test |
| Explicit Run ID와 no latest | `test_invalid_run_id_and_missing_run_id_return_invalid_input_exit_code` |
| Public package resource와 contract sync | `VerdictContractCoherenceTests`, CLI/package resource test, `scripts/sync_contracts.py --check` |
| 이중언어 public 문서 | `tests/test_docs.py`의 1:1 pair, reciprocal selector, local link, 같은 언어 navigation test |

`tests/test_codex_permissions.py`는 별도 Codex credential profile을 보호한다. Core
characterization dependency cone 밖이므로 재구현하지 않고 보존한다.

## 새 Characterization Test

R0a는 기존에 없던 경계만 추가한다.

- passing, required-failure, timeout, Scope-violation Run이 정확히
  `ValidatedRun`인지 명시적으로 검사한다.
- Run directory를 repository 밖으로 옮긴 뒤 logical Run path를 symlink로 바꾸는 POSIX
  Evidence directory escape를 거부한다.
- Windows drive absolute 형식인 `C:/...` Evidence path를 거부한다.
- Required check failure를 성공적으로 기록한 `verify`가 exit 0을 반환하면서 저장
  mechanical result는 `fail`임을 CLI에서 검사한다.

이 테스트들은 production behavior를 바꾸지 않는다.

## Known-gap executable test

다음 한계가 실제 baseline에 있으므로 일반 discovery test 두 개를
`unittest.expectedFailure`로 표시한다.

1. `test_complete_rejects_product_source_changes_after_verification`은 verify 이후 source가
   바뀌면 completion이 거부돼야 한다는 원하는 계약을 표현한다. 현재 complete는 저장
   Evidence만 읽고 `completion.json`을 성공적으로 쓰므로 실패한다.
2. `test_verify_cannot_override_task_baseline_to_hide_product_changes`는 Task 이후 Scope 밖
   commit을 만들고 `--base-ref HEAD`로 verify한다. 현재 Run이 뒤의 HEAD를 baseline으로
   기록하고 post-Task change를 숨기므로 실패한다.

R1b가 source binding과 baseline rule을 구현하면 decorator를 제거해야 한다. 두 번째
test는 `--base-ref` 거부 또는 원 Task baseline과 보이는 change 기록 중 어느 방식으로
고쳐져도 unexpected success가 되어 decorator 제거 전까지 suite를 실패시킨다.

## 알려진 계약

- `validate_run()`은 저장 Evidence의 내부 무결성을 검증한다.
- Required check failure, timeout, Scope violation, mechanical fail은 저장 record가 모두
  일치하면 corrupted Evidence가 아니다.
- 이러한 Run도 `ValidatedRun`이며 bundle이나 Manual Verdict의 대상이 될 수 있다.
- Completion policy는 Scope, timeout, required-check failure를 stable exit 4, 6, 5로
  별도 거부한다.
- Bundle은 check를 재실행하거나 Git state를 다시 수집하지 않는다.
- Bundle, completion, Verdict consumer는 먼저 `validate_run()`을 통과한다.
- Optional verifier라도 기록된 `fail`, `unable`, blocker를 무시하지 않는다.
- `complete --run-id`는 explicit Run을 요구하며 implicit latest selection은 없다.
- Current Working Tree 또는 current-source binding은 제공하지 않는다.
- `--base-ref`는 공개된 v0.1.1 한계로 남아 있다.
- Run manifest는 local consistency identifier이지 signature, attestation, immutable
  ledger, external trust anchor가 아니다.

## R0b Refactoring boundary

### 반드시 분리할 책임

1. `evidence.py` 안의 mechanical Evidence 생산과 completion policy/completion record
   write를 분리한다.
2. `validate_run(task_id, run_id, cwd=...)`을 유일한 public façade로 유지하면서 내부의
   safe artifact access, document별 validation, check/scope/result cross-document
   consistency, immutable `ValidatedRun` assembly를 분리한다.
3. Validator, manifest, Verdict persistence, bundle consumption이 사용하는 하나의
   구체적인 strict Run-artifact confinement/read 경계를 만든다. Generic repository나
   service abstraction으로 만들지 않는다.
4. Dependency cone 안에서 Run ID validation과 순수 Harness metadata/path-boundary policy를
   canonical하게 만든다.

### 유지할 책임

- Public `validate_run()` signature, `ValidatedRun`, error-to-exit 의미
- `task`의 Task/check normalization
- `gitdiff`의 live Git collection과 `checks`의 process lifecycle
- `run_manifest`의 raw-byte Evidence digest authority
- `verdict_validator`의 packaged Verdict Schema authority
- `ValidatedRun` consumer로서 bundle portability와 completion policy
- 현재 CLI JSON, artifact filename, Schema version, stable exit code

### R0b dependency cone에서 삭제할 중복

- Verdict의 별도 Run ID 상수와 validator
- Validator와 manifest 사이의 strict Evidence path/read 복사
- 복사된 Harness metadata 상수와 component-boundary predicate
- 현재 의미가 동등하다고 characterization된 범위의 ordinary atomic JSON/bytes writer

### 의도적으로 건드리지 않을 구조 문제

- Source Snapshot과 current-source binding
- `--base-ref` 제거 또는 의미 변경
- Task, Evidence, Verdict, Bundle Schema나 exit code 변경
- Check 실행과 Windows Job/process-tree 동작
- Bundle size limit과 완전한 secret redaction
- External verifier, LLM, credential, retry, provider adapter
- Ledger, hook, approval state, runtime monitoring, Agent topology
- Generic repository, service layer, registry, placeholder module
- 줄 수 감소를 위한 `checks.py`, `gitdiff.py` 기계적 분할

## 이번 Phase 밖의 기록된 위험

- Bundle log copy가 검증된 path를 다시 읽으므로 concurrent replacement에 대한
  check-to-copy TOCTOU window가 있다.
- 저장 Verdict read가 strict Run confinement helper를 사용하지 않아 사후 symlink가
  외부의 valid Verdict document를 가리킬 수 있다.
- 저장 Task snapshot 자체도 symlink confinement 없이 읽는다.
- Repository-root 구현 세 개의 Git/worktree 의미가 서로 다르다.
- `show_task()`는 저장 snapshot 전체를 재검증하거나 document ID를 완전히 비교하지 않는다.
- Task `--force`는 Evidence/Verdict의 atomic replacement와 달리 직접 write한다.
- `validate_run()`은 Run integrity에 필요한 Task field만 검증하고 원래 Task contract
  전체를 재검증하지 않는다.
- CI는 Ubuntu/Python 3.11만 사용하므로 모든 지원 platform과 3.11 이후 Python을 직접
  검증하지 않는다.

이 항목은 감사 결과이지 R0a에서 behavior를 바꿀 권한이 아니다.

## R0a에서 기록한 검증

| Command 또는 check | 실제 결과 |
| --- | --- |
| `.release-venv/bin/python -m pip install -e '.[test]'` | 첫 sandbox 실행은 PyPI DNS 불가로 exit 1, 승인된 재실행은 exit 0이며 editable `outcome-harness 0.1.1` 설치 |
| `.release-venv/bin/python scripts/sync_contracts.py --check` | Exit 0 |
| Docs, Run integrity, completion targeted suite | 40 tests, exit 0, expected failure 2 |
| `PYTHONPATH=src .release-venv/bin/python -m unittest discover -s tests -v` | 143 tests, exit 0, skip 3, expected failure 2 |
| `git diff --check` | Exit 0 |
| `git diff --check HEAD^ HEAD` | Exit 0 |
| `.release-venv/bin/python -m build --wheel --outdir <TEMP>` | 첫 isolated build는 PyPI DNS 불가로 exit 1, 승인된 재실행은 exit 0이며 `outcome_harness-0.1.1-py3-none-any.whl` 생성 |
| `.release-venv/bin/python -m venv`로 새 clean venv 생성 | Exit 0 |
| Clean venv에 생성 wheel 설치 | 첫 sandbox 실행은 PyPI dependency resolve 불가로 exit 1, 승인된 재실행은 exit 0 |
| 설치된 `harness --help` | Exit 0 |
| 설치된 `harness --version` | Exit 0, `harness 0.1.1` |
| 설치 package에서 `import harness`, `validate_run`, `validate_verdict` | Exit 0 |
| Packaged `verdict.schema.json` parse와 `verifier.md` read | Exit 0 |

Skip 세 건은 macOS filesystem에서 만들 수 없는 non-UTF-8 byte filename 두 건과 현재
process가 시작할 수 없는 nested Codex sandbox smoke 한 건이다. Expected failure 두 건은
앞에서 설명한 source-binding과 `--base-ref` executable gap이다. 이 macOS host에서는
Windows E2E를 실행하지 않았다.
