# Harness architecture

Language: [English](architecture.md) | 한국어

이 문서는 unreleased current main `0.2.0.dev0`을 설명한다. v0.1.1은 최신
published release이며 historical non-source-bound completion 동작을 유지한다.

## 책임 경계

Harness는 coding Agent의 작업 과정, tool 호출, reasoning, runtime state를 제어하지 않는다. 이 도구의 책임은 특정 Task에 대해 저장된 변경·check 결과·Manual Verdict를 읽을 수 있는 Evidence로 남기고, 저장 Run의 integrity와 completion policy를 분리해 판정하는 데 있다.

이 경계는 두 가지를 분리한다.

- 구현자가 만든 변경과 Harness가 수집한 mechanical result
- 사람이 제공한 Manual Verdict와 Harness가 수행하는 저장·재검증·completion gate

Harness는 Manual Verdict를 생성하거나 verifier의 독립성을 보장하지 않는다. 현재 제공하는 verifier 경로는 사용자가 제출한 JSON을 record하고 show하는 manual 경로뿐이다.

## 모듈별 책임

| 모듈 | 책임 |
| --- | --- |
| harness.cli | CLI 인자를 명령별 함수로 연결하고 stable exit code를 반환 |
| harness.task | Task Spec과 check catalog를 읽고 Task snapshot 및 baseline을 저장 |
| harness._path_policy (내부) | producer와 validator 입력 정규화 방식을 합치지 않으면서 순수 component boundary와 Harness metadata path policy를 공유 |
| harness.gitdiff | baseline과 현재 working tree 사이의 product 변경 및 scope 정보를 수집 |
| harness.source_snapshot | 유일한 live canonical product-source Snapshot을 수집하고 persisted Snapshot document를 parse·validate |
| harness.checks | argv 배열로 check를 실행하고 stdout과 stderr를 Run 내부에 기록 |
| harness._run_artifact_io (내부) | relative Run artifact path를 검증하고 confined raw byte를 읽으며 document 의미를 해석하지 않는 기존 atomic Run artifact writer를 제공 |
| harness.run_manifest | mechanical Evidence raw byte의 크기·SHA-256·canonical `evidence_sha256`을 생성하고 비교 |
| harness._run_documents (내부) | 저장 document shape와 document 사이의 check, scope, source stability, mechanical result consistency를 검증 |
| harness._source_binding_documents (내부) | Persisted S0/S1 Snapshot file을 confined read·parse하고 Task baseline, digest, stability를 frozen `StoredSourceBinding` 하나로 교차 검증 |
| harness.run_validator | 유일한 public stored-Run integrity façade로 남아 Task/Run을 찾고 내부 validator를 조정해 immutable `ValidatedRun`을 조립 |
| harness.evidence | Check execution 전후 S0/S1을 수집하고 versioned mechanical Evidence를 생성하면서 기존 verification 및 completion public import를 유지 |
| harness._source_binding (내부) | Complete-time 경계만 적용해 legacy, current collection, historical/current mismatch failure를 구분하고 canonical live API로 S2를 수집 |
| harness._completion (내부) | `ValidatedRun`과 저장 Verdict evidence를 소비해 completion policy를 적용하고 `completion.json`을 atomic하게 저장 |
| harness.bundle | validated Run의 제한된 Evidence와 packaged verifier instruction으로 portable bundle 생성 |
| harness.verdict_validator | packaged Verdict Schema를 사용해 Verdict 구조와 format, Task/run context를 검증 |
| harness.verdict | Manual Verdict의 raw 원본 보존, canonical snapshot 저장, 재검증, finding count 계산 |

Underscore로 시작하는 module은 새 public API가 아니라 private 구현 경계다. 기존 caller는
저장 Run integrity에 `harness.run_validator.validate_run()`을 계속 사용하고 verification과
completion에는 `harness.evidence` 아래의 기존 이름을 사용한다. Bundle, Verdict,
completion code는 private document validator를 별도 authority처럼 직접 호출하지 않는다.

`harness._run_documents`는 큰 module이지만 하나의 persisted-document trust
transaction으로 의도적으로 유지한다. Task, changed-files, check, verification,
log document는 파생된 scope와 mechanical result를 신뢰하기 전에 함께 읽고
교차 검증해야 한다. 지금 이 검사를 나누면 중간 전달 객체나 독립적으로 호출
가능한 partial validator가 필요해져 같은 integrity invariant의 ownership이
분산되고 대체 내부 validation 경로가 생긴다. 추가 extraction은 하나의 책임이
독립된 입력·출력과 Characterization Test를 가지면서도 public `validate_run()`
façade에서만 조합될 수 있을 때 수행한다. 파일 크기만으로는 그 경계가 되지
않는다.

Root의 `schemas/verdict.schema.json`과 `prompts/verifier.md`는 사람이 편집하는
canonical contract다. `src/harness/resources` 아래의 같은 파일은 package에
포함되는 mirror이며 `scripts/sync_contracts.py`가 byte-for-byte 동기화를 확인한다.
`schemas/verification.schema.json`은 exact version 1/version 2 persisted
verification record를 정의하지만 두 번째 live Snapshot API는 아니다.

## Task에서 completion까지의 흐름

    Task Spec
       │ task create
       ▼
    Task snapshot + baseline
       │ verify: S0 → checks → S1
       ▼
    Evidence Run v2
       ├── source-before-checks.json (S0)
       ├── source-after-checks.json (S1)
       ├── mechanical result
       ├── verifier bundle
       └── Manual Verdict record
                │
                │ stored Run + Verdict validate
                ▼
             complete: S2 수집 → source gate → policy gate

`task create`는 Task Spec을 snapshot으로 저장하고 그 시점의 Git HEAD를 full
baseline commit으로 남긴다. Current-main `verify`는 이 saved baseline만 사용하며
Run 단위 `--base-ref` override와 그 Python API는 제거했다. Task-baseline
revision과 CI pull-request base/head 선택은 implicit fallback이 아니다. `bundle`은
저장된 Run을 다시 실행하거나 S2를 수집하지 않고 검토에 필요한 제한된 persisted
payload만 export한다.

complete, bundle, verifier record/show는 먼저 특정 Task/run을 `validate_run()`으로 읽는다. 이 validator는 check나 Git diff를 다시 계산하지 않으며 latest-run 선택도 하지 않는다.

## Run integrity와 completion policy

`validate_run()`은 저장 Run이 자기모순 없이 읽히는지만 판정한다.
Required-check failure, timeout, Scope violation, S0/S1 source instability,
`mechanical_result="fail"`은 실패한 작업 결과일 수 있지만 손상된 Evidence는
아니다. 따라서 이러한 Run도 `ValidatedRun`으로 반환되며 bundle export와 Manual
Verdict 기록의 대상이 될 수 있다.

Completion source binding과 policy는 이후의 별도 책임이다. v2 stored Run이
valid하고 기록된 Verdict integrity도 valid하면 `complete`가 current product
source를 S2로 수집한다. Source-bound v2 Run은 Scope pass, required-check pass,
timeout 없음, required Verdict와 blocker 조건을 적용하기 전에 S0 = S1 = S2를
만족해야 한다. v1 completion path는 S2를 수집하지 않고 exit 9로 fail-closed한다.
Completion 거부는 Run integrity와 Git collection 오류와 구분되어 stable exit
code로 표현된다.

Validator는 저장된 `.harness/tasks/<TASK_ID>.json`과 Run 내부 artifact만 읽는다.
현재 source tree를 수집하거나 Git diff를 재생성하지 않고 check를 재실행하지
않는다. 별도 complete-time 경계만 S2를 수집한다. 어느 경계도 Agent의 tool
사용·승인·worktree·repair 흐름을 통제하지 않는다.

## Mechanical result와 Manual Verdict

Verification v2의 mechanical result는 scope pass, required-check pass, S0/S1
source stability에서 계산된다. Manual Verdict는 mechanical result와 별도의
입력이며 이를 덮어쓰거나 보정하지 않는다.

completion은 다음을 함께 본다.

- 저장된 Task/run identity와 Evidence의 일치
- scope, required check 결과, source stability, mechanical result의 consistency
- S0, S1, current S2가 같은 source-bound v2 Run
- verifier가 required인 경우 valid pass Verdict와 blocker 0개
- verifier가 optional인 경우에도 기록된 fail, unable, blocker Verdict를 무시하지 않음

warning과 note finding은 completion record에 count로 남지만, 그 자체로 completion을 막지는 않는다.

## Evidence directory

    .harness/evidence/<TASK_ID>/<RUN_ID>/
    ├── task.json
    ├── changed-files.json
    ├── diff.patch
    ├── checks.json
    ├── checks/
    │   ├── <check>.stdout
    │   └── <check>.stderr
    ├── source-before-checks.json
    ├── source-after-checks.json
    ├── verification.json
    ├── run-manifest.json
    ├── verdict.raw.json
    ├── verdict.json
    └── completion.json

Base mechanical Evidence file, 두 Snapshot document, check log는 `verify`가 만든다.
`run-manifest.json`은 이 mechanical file의 raw-byte record를 모아 verification
마지막 단계에 저장한다. Verdict file은 `verifier record` 성공 뒤에만 생기며
`completion.json`은 `complete`가 모든 gate를 통과했을 때만 생긴다. Manifest에는
자신, Verdict, Completion, ephemeral S2를 넣지 않는다.

S0 collection은 check와 Run directory 생성 전에 수행한다. S1 collection 또는
이후 persistence가 실패하면 valid manifest나 성공 stdout result가 생기지 않는다.
진단을 위해 incomplete UUID directory와 이미 기록된 log가 남을 수 있다.

## 현재 integrity model

현재 모델은 `validate_run()`을 저장 mechanical Evidence의 단일 integrity boundary로 사용한다.

- 요청 Task/run identity, saved Task snapshot, Run `task.json`, `verification.json` identity를 비교한다.
- required Evidence 파일, JSON readability, listed Evidence path, log 존재, Run directory 밖 symlink 탈출을 확인한다.
- Task check 정의와 recorded check 결과, `passed`·`timed_out`·`exit_code` 관계를 확인한다.
- changed-files baseline/product change/scope violation과 `scope_pass`, `required_checks_pass`, `mechanical_result`를 저장 자료로 다시 계산해 비교한다.
- Verification v2에서는 S0/S1을 parse하고 공통 full Task baseline을 요구하며, digest를 verification record와 비교한 뒤 `source_stable_during_checks`와 source-aware mechanical result를 다시 계산한다.
- expected mechanical file list와 `run-manifest.json`의 sorted record를 비교하고, 각 raw byte size·SHA-256과 timestamp를 제외한 canonical `evidence_sha256`을 다시 계산한다.

`validate_run()` 반환 이후 Verdict consumer가 raw Verdict와 normalized
snapshot을 별도의 Verdict contract로 다시 validate하고 서로 같은지 확인한다.
Completion은 validated Run의 `evidence_sha256`을 기록하고, bundle은 이를
`source_evidence_sha256`으로 기록한 뒤 portable payload의 별도
`bundle_sha256`을 만든다.

이것은 cryptographic provenance 또는 immutable storage가 아니다. manifest는 verify 이후 mechanical file의 수정·누락·교체를 탐지하지만, 동일한 로컬 사용자가 Evidence와 manifest를 함께 다시 계산해 편집하는 것을 막지 못한다. `evidence_sha256`과 bundle hash는 completion authority나 remote attestation이 아니다.

## Source Snapshot과 binding 경계

`harness.source_snapshot.collect_source_snapshot()`은 유일한 live collection
API로 남는다. 저장된 Task baseline 대비 product source의 deterministic read-only
identity를 계산하고, committed/staged/unstaged transition을 final Working Tree
결과로 합치며, non-ignored untracked product file을 포함하고 canonical Harness
metadata를 제외하며 identity를 Task Scope로 제한하지 않는다.
[ADR 0004](adr/0004-canonical-source-snapshot.ko.md)는 entry, digest, symlink,
special-file, bounded-observation semantics를 정의한다.

R1b는 변경하지 않은 collector를 세 위치에서 호출한다.

- S0: check 직전
- S1: 모든 check 종료 직후
- S2: `complete`에서 persisted Evidence와 recorded Verdict integrity validation 뒤

새 Run은 `verification.json` schema version 2를 사용하고 S0/S1을 raw-byte
manifest가 포함하는 Source Snapshot schema-version-1 document로 저장한다. 나머지
기존 document schema version은 모두 1을 유지한다. `validate_run()`은 verification
v1/v2를 dispatch해 stored value를 반환하며 S2를 수집하지 않는다. Former baseline
override로 만든 historical Run을 포함한 valid v1 Run은 계속 review·bundle할 수
있지만 upgrade하지 않고 current-source-bound completion을 exit 9로 거부한다.
Version 2는 Task, changed-files, verification, S0, S1 baseline이 같은 full commit
SHA일 것을 요구한다.

Complete-time binding은 S0/S1 instability와 S1/S2 mismatch를 exit 9로 거부한다.
Current repository 또는 Snapshot collection failure는 exit 3이고, missing,
malformed, tampered, contradictory stored Snapshot Evidence는 exit 8이다. Binding
성공 뒤에만 기존 order인 verifier 7, scope 4, required timeout 6,
required-check failure 5를 적용한다. Bundle은 historical S0/S1을 포함하지만 S2를
수집하거나 current-source authority가 되지 않는다.

이 비교는 filesystem transaction이나 lock이 아닌 bounded observation이다.
Collector는 ADR 0004가 설명한 supported race를 탐지하지만 S2 관찰 뒤 또는
`complete` 반환 뒤 source가 바뀌는 것을 막지 않는다. Local manifest도 동일한
local user가 Evidence 전체를 다시 계산해 쓰는 공격을 막지 못한다.

Check output에는 민감한 값이 있을 수 있다. Harness는 absolute path를 portable하게
정리하려고 하지만 완전한 secret redaction을 제공하지 않는다.

## 외부 adapter를 core와 분리하는 이유

core는 로컬 파일, Git, argv 기반 check, deterministic Schema validation만 다룬다. 외부 모델 API, vendor verifier CLI, network retry, credential 처리, 비용·지연 정책은 이 경계 밖의 adapter 책임이다.

이 분리는 core Evidence contract가 특정 vendor의 응답 형식이나 network 상태에 흔들리지 않게 한다. 외부 adapter가 필요해지면 versioned input/output contract, failure mode, provenance를 별도로 설계한 뒤 core와 연결해야 한다.
