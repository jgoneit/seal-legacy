# Outcome Harness architecture

## 책임 경계

Outcome Harness는 coding Agent의 작업 과정, tool 호출, reasoning, runtime state를 제어하지 않는다. 이 도구의 책임은 특정 Task에 대해 저장된 변경·check 결과·Manual Verdict를 읽을 수 있는 Evidence로 남기고, 그 Evidence로 completion을 fail-closed로 판정하는 데 있다.

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
| harness.evidence | mechanical Evidence를 저장하고 completion에 필요한 일관성을 판정 |
| harness.bundle | 선택한 Run의 제한된 Evidence와 packaged verifier instruction으로 portable bundle 생성 |
| harness.run_validator | packaged Verdict Schema를 사용해 Verdict 구조와 format, Task/run context를 검증 |
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

task create는 Task Spec을 snapshot으로 저장하고 그 시점의 Git HEAD를 baseline으로 남긴다. verify는 check를 실행하고 baseline부터 현재 working tree까지의 scope 관련 변경을 Run directory에 저장한다. bundle은 저장된 Run을 다시 실행하지 않고 검토에 필요한 제한된 payload만 export한다.

complete는 특정 Task/run을 명시적으로 받아 저장된 Evidence를 다시 읽는다. check나 Git diff를 다시 계산하지 않으며 latest-run 선택도 하지 않는다.

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
    ├── verdict.raw.json
    ├── verdict.json
    └── completion.json

앞의 다섯 mechanical Evidence 파일과 check log는 verify가 만든다. Verdict 파일은 verifier record가 성공한 후에만 생긴다. completion.json은 complete가 모든 gate를 통과했을 때만 생긴다.

## 현재 integrity model

현재 모델은 저장된 artifact 사이의 기본 연결을 검사한다.

- Task/run identity를 명시적으로 전달하고 저장된 Evidence와 비교한다.
- required Evidence 파일의 존재와 JSON parse 가능 여부를 확인한다.
- required check 결과, mechanical result, scope 결과가 서로 모순되지 않는지 확인한다.
- raw Verdict를 다시 validate하고 canonical snapshot을 다시 validate한 뒤 두 validated 값이 같은지 확인한다.
- bundle은 선택한 Run의 제한된 payload와 manifest hash를 만든다.

이것은 cryptographic provenance 또는 immutable storage가 아니다. 동일한 로컬 사용자가 Evidence와 관련 artifact를 함께 편집하는 것을 막지 못하며, bundle hash도 completion authority나 remote attestation이 아니다.

## 알려진 한계와 다음 설계 경계

현재는 verification 당시의 source와 나중의 source가 같은지 binding하지 않는다. 전체 Evidence manifest와 digest, pre/post check snapshot 비교, snapshot fingerprint도 아직 없다. 따라서 complete가 "현재 source"를 재검증한다고 해석하면 안 된다.

check output에는 민감한 값이 있을 수 있다. Harness는 절대 경로를 portable하게 정리하려고 하지만 complete secret redaction을 제공하지 않는다.

향후 snapshot binding은 Run integrity를 확장하는 별도 기능으로 다뤄야 한다. 그것은 현재 Verdict 구조 validation과 다른 책임이며, 이 문서의 현재 흐름에 암묵적으로 포함되지 않는다.

## 외부 adapter를 core와 분리하는 이유

core는 로컬 파일, Git, argv 기반 check, deterministic Schema validation만 다룬다. 외부 모델 API, vendor verifier CLI, network retry, credential 처리, 비용·지연 정책은 이 경계 밖의 adapter 책임이다.

이 분리는 core Evidence contract가 특정 vendor의 응답 형식이나 network 상태에 흔들리지 않게 한다. 외부 adapter가 필요해지면 versioned input/output contract, failure mode, provenance를 별도로 설계한 뒤 core와 연결해야 한다.
