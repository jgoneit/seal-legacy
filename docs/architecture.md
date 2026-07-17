# Outcome Harness architecture

## 책임 경계

Outcome Harness는 coding Agent의 작업 과정, tool 호출, reasoning, runtime state를 제어하지 않는다. 이 도구의 책임은 특정 Task에 대해 저장된 변경·check 결과·Manual Verdict를 읽을 수 있는 Evidence로 남기고, 저장 Run의 integrity와 completion policy를 분리해 판정하는 데 있다.

이 경계는 두 가지를 분리한다.

- 구현자가 만든 변경과 Harness가 수집한 mechanical result
- 사람이 제공한 Manual Verdict와 Harness가 수행하는 저장·재검증·completion gate

Harness는 Manual Verdict를 생성하거나 verifier의 독립성을 보장하지 않는다. 현재 제공하는 verifier 경로는 사용자가 제출한 JSON을 record하고 show하는 manual 경로뿐이다.

## 모듈별 책임

| 모듈 | 책임 |
| --- | --- |
| harness.cli | CLI 인자를 명령별 함수로 연결하고 stable exit code를 반환 |
| harness.task | Task Spec과 check catalog를 읽고 Task snapshot 및 baseline을 저장 |
| harness.gitdiff | baseline과 현재 working tree 사이의 product 변경 및 scope 정보를 수집 |
| harness.checks | argv 배열로 check를 실행하고 stdout과 stderr를 Run 내부에 기록 |
| harness.run_manifest | mechanical Evidence raw byte의 크기·SHA-256·canonical `evidence_sha256`을 생성하고 비교 |
| harness.run_validator | 저장된 Task/Run Evidence의 identity, path, check, scope, mechanical result consistency를 canonical하게 검증 |
| harness.evidence | mechanical Evidence를 저장하고 validated Run의 completion policy 및 completion record를 처리 |
| harness.bundle | validated Run의 제한된 Evidence와 packaged verifier instruction으로 portable bundle 생성 |
| harness.verdict_validator | packaged Verdict Schema를 사용해 Verdict 구조와 format, Task/run context를 검증 |
| harness.verdict | Manual Verdict의 raw 원본 보존, canonical snapshot 저장, 재검증, finding count 계산 |

root의 schemas/verdict.schema.json과 prompts/verifier.md는 사람이 편집하는 canonical contract다. src/harness/resources 아래의 같은 파일은 package에 포함되는 mirror이며 scripts/sync_contracts.py가 byte-for-byte 동기화를 확인한다.

## Task에서 completion까지의 흐름

    Task Spec
       │ task create
       ▼
    Task snapshot + baseline
       │ verify
       ▼
    Evidence Run
       ├── mechanical result
       ├── verifier bundle
       └── Manual Verdict record
                │
                ▼
             complete

task create는 Task Spec을 snapshot으로 저장하고 그 시점의 Git HEAD를 baseline으로 남긴다. verify는 기본적으로 이 baseline부터 현재 working tree까지의 scope 관련 변경을 Run directory에 저장한다. v0.1.0에서는 optional `--base-ref`가 해당 Run의 baseline을 override할 수 있으며, 이는 공개된 알려진 한계다. bundle은 저장된 Run을 다시 실행하지 않고 검토에 필요한 제한된 payload만 export한다.

complete, bundle, verifier record/show는 먼저 특정 Task/run을 `validate_run()`으로 읽는다. 이 validator는 check나 Git diff를 다시 계산하지 않으며 latest-run 선택도 하지 않는다.

## Run integrity와 completion policy

`validate_run()`은 저장 Run이 자기모순 없이 읽히는지만 판정한다. 필수 check 실패, timeout, Scope violation, `mechanical_result="fail"`은 실패한 작업 결과일 수 있지만 손상된 Evidence는 아니다. 따라서 이러한 Run도 `ValidatedRun`으로 반환되며 bundle export와 Manual Verdict 기록의 대상이 될 수 있다.

completion policy는 그 다음 단계의 별도 책임이다. `complete`는 이미 유효하다고 판정된 Run에 대해 Scope pass, required check pass, timeout 없음, required Verdict와 blocker 조건을 적용한다. completion 거부는 Run integrity 오류와 구분되어 stable exit code로 표현된다.

validator는 저장된 `.harness/tasks/<TASK_ID>.json`과 Run 내부 artifact만 읽는다. 현재 source tree를 수집하거나 Git diff를 재생성하지 않고, check를 재실행하지 않으며, Agent의 tool 사용·승인·worktree·repair 흐름도 통제하지 않는다.

## Mechanical result와 Manual Verdict

Mechanical result는 scope pass와 required check 결과에서 계산된다. Manual Verdict는 mechanical result와 별도의 입력이며, 이를 덮어쓰거나 보정하지 않는다.

completion은 다음을 함께 본다.

- 저장된 Task/run identity와 Evidence의 일치
- scope와 required check 결과의 consistency
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
    ├── verification.json
    ├── run-manifest.json
    ├── verdict.raw.json
    ├── verdict.json
    └── completion.json

앞의 다섯 mechanical Evidence 파일과 check log는 verify가 만든다. `run-manifest.json`은 이 mechanical 파일들의 raw byte record를 모아 verify의 마지막 단계에서 저장한다. Verdict 파일은 verifier record가 성공한 후에만 생기며, completion.json은 complete가 모든 gate를 통과했을 때만 생긴다. manifest에는 자신, Verdict, Completion을 넣지 않는다.

## 현재 integrity model

현재 모델은 `validate_run()`을 저장 mechanical Evidence의 단일 integrity boundary로 사용한다.

- 요청 Task/run identity, saved Task snapshot, Run `task.json`, `verification.json` identity를 비교한다.
- required Evidence 파일, JSON readability, listed Evidence path, log 존재, Run directory 밖 symlink 탈출을 확인한다.
- Task check 정의와 recorded check 결과, `passed`·`timed_out`·`exit_code` 관계를 확인한다.
- changed-files baseline/product change/scope violation과 `scope_pass`, `required_checks_pass`, `mechanical_result`를 저장 자료로 다시 계산해 비교한다.
- expected mechanical file list와 `run-manifest.json`의 sorted record를 비교하고, 각 raw byte size·SHA-256과 timestamp를 제외한 canonical `evidence_sha256`을 다시 계산한다.
- raw Verdict와 normalized snapshot은 별도의 Verdict contract로 다시 validate하고 서로 같은지 확인한다.
- completion은 validated Run의 `evidence_sha256`을 기록하고, bundle은 이를 `source_evidence_sha256`으로 기록한 뒤 portable payload의 별도 `bundle_sha256`을 만든다.

이것은 cryptographic provenance 또는 immutable storage가 아니다. manifest는 verify 이후 mechanical file의 수정·누락·교체를 탐지하지만, 동일한 로컬 사용자가 Evidence와 manifest를 함께 다시 계산해 편집하는 것을 막지 못한다. `evidence_sha256`과 bundle hash는 completion authority나 remote attestation이 아니다.

## 알려진 한계와 다음 설계 경계

현재는 verification 당시의 source와 나중의 source가 같은지 binding하지 않는다. manifest는 당시 저장된 mechanical Evidence의 local consistency만 확인하며, diff와 changed-files의 의미적 binding, pre/post check snapshot 비교, snapshot fingerprint는 아직 없다. 따라서 `validate_run()`이나 `complete`가 "현재 source"를 재검증한다고 해석하면 안 된다.

`verify --base-ref`는 저장된 Task baseline 대신 별도 Git ref를 그 Run의 baseline으로 기록할 수 있다. 이 옵션은 v0.1.0에서 유지되는 명시적 override이며, source binding이나 Task baseline 불변성을 제공하지 않는다.

check output에는 민감한 값이 있을 수 있다. Harness는 절대 경로를 portable하게 정리하려고 하지만 완전한 secret redaction을 제공하지 않는다.

향후 snapshot binding은 Run integrity를 확장하는 별도 기능으로 다뤄야 한다. 그것은 현재 Verdict 구조 validation과 다른 책임이며, 이 문서의 현재 흐름에 암묵적으로 포함되지 않는다.

## 외부 adapter를 core와 분리하는 이유

core는 로컬 파일, Git, argv 기반 check, deterministic Schema validation만 다룬다. 외부 모델 API, vendor verifier CLI, network retry, credential 처리, 비용·지연 정책은 이 경계 밖의 adapter 책임이다.

이 분리는 core Evidence contract가 특정 vendor의 응답 형식이나 network 상태에 흔들리지 않게 한다. 외부 adapter가 필요해지면 versioned input/output contract, failure mode, provenance를 별도로 설계한 뒤 core와 연결해야 한다.
