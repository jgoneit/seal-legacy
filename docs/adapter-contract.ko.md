# Harness Adapter CLI Contract

Language: [English](adapter-contract.md) | 한국어

이 문서는 Codex Plugin을 포함한 thin adapter가 current main의 unreleased Harness
Core `0.2.0.dev0`을 subprocess로 호출할 때의 공개 계약이다. v0.1.1은 여전히 최신
published Experimental release이며 legacy non-source-bound completion 계약을
사용한다. Adapter는 Core Python package를 import하지 않고, 아래 CLI와 stdout
JSON만 사용해야 한다.

## Public CLI

| Command | Required arguments |
| --- | --- |
| `harness --version` | 없음 |
| `harness task create` | `--file <TASK_JSON>` |
| `harness task show` | `<TASK_ID>` |
| `harness verify` | `<TASK_ID>` |
| `harness verifier bundle` | `<TASK_ID> --run-id <RUN_ID> --output <DIR>` |
| `harness verifier record` | `<TASK_ID> --run-id <RUN_ID> --file <VERDICT_JSON>` |
| `harness verifier show` | `<TASK_ID> --run-id <RUN_ID>` |
| `harness complete` | `<TASK_ID> --run-id <RUN_ID>` |

Current main은 `verify --base-ref`, hidden alias, environment fallback을 지원하지
않는다. `--base-ref`를 전달하면 invalid argparse input으로 exit 2를 반환한다.
Verification은 항상 Task snapshot에 저장된 full baseline commit을 사용한다. Task
baseline revision과 CI 전용 base/head 선택은 별도의 unsupported concern이다.

## Success stdout

`--version`과 `--help`를 제외한 위 command의 성공 stdout은 UTF-8 JSON object 하나다.
성공 중 diagnostic text가 stdout JSON에 추가되지 않는다. `--version`과 `--help`의
plain-text 출력은 정상적인 예외다.

| Command | Required success JSON fields |
| --- | --- |
| `task create` | `schema_version`, `id`, `type`, `objective`, `scope`, `checks`, `risk`, `verifier`, `baseline` |
| `task show` | `schema_version`, `id`, `type`, `objective`, `scope`, `checks`, `risk`, `verifier`, `baseline` |
| `verify` | `run_id`, `evidence_path` |
| `verifier bundle` | `task_id`, `run_id`, `bundle_path`, `manifest_path`, `total_size_bytes`, `bundle_sha256` |
| `verifier record` | `task_id`, `run_id`, `raw_verdict_path`, `verdict_path` |
| `verifier show` | `schema_version`, `task_id`, `run_id`, `verifier`, `verdict`, `summary`, `findings`, `reviewed_at` |
| `complete` | `task_id`, `run_id`, `completion_path` |

Path field는 실행한 repository의 local absolute path일 수 있다. Adapter는 이를 opaque
local path로 취급하고 다른 host 또는 repository에 재사용해서는 안 된다.

## stderr and exit codes

정상 결과는 exit code `0`과 stdout JSON을 함께 반환한다. handled error는 stderr에
`error: <message>` 형식으로 기록하며 성공 JSON을 stdout에 섞지 않는다. `harness`,
`harness task`, `harness verifier`처럼 required command 또는 subcommand가 생략된 형태를
포함해 argparse가 거부하는 입력은 반드시 usage text를 stderr에 쓰고 exit `2`를 반환한다.
이 경우 stdout에는 JSON을 포함하지 않는다.

실패한 command가 partial success JSON을 반환한다고 가정해서는 안 된다. 특히 `verify`가
중간에 실패하면 evidence directory가 남을 수 있어도 Adapter는 nonzero exit를 실패로
처리하고 stdout JSON을 결과로 소비하지 않는다.

| Exit code | Meaning |
| ---: | --- |
| 0 | success |
| 2 | invalid input or schema |
| 3 | Git or repository error |
| 4 | scope violation at completion |
| 5 | required check failure at completion |
| 6 | required check timeout at completion |
| 7 | verifier gate not satisfied |
| 8 | evidence missing or corrupt |
| 9 | source binding not satisfied |

이 숫자의 기존 의미는 stable contract다. 자세한 completion 판정 순서는
[Exit codes](exit-codes.ko.md)를 따른다.

## Public read-only artifacts

Adapter의 기본 경계는 CLI/JSON이다. Evidence를 보여주거나 archive해야 하는
경우에만 아래 current-main read-only artifact surface를 사용할 수 있다. Adapter는
이 파일을 만들거나 수정해서는 안 된다.

| Location | Documented purpose and fields |
| --- | --- |
| `.harness/tasks/<TASK_ID>.json` | Task snapshot; `task create`/`task show`와 같은 Task JSON fields |
| `<evidence_path>/verification.json` | Versioned Run identity와 mechanical outcome; v1은 legacy field, v2는 `source_snapshot_schema_version`, `source_before_checks_sha256`, `source_after_checks_sha256`, `source_stable_during_checks`도 포함 |
| `<evidence_path>/source-before-checks.json` | Source Snapshot schema version 1을 사용하는 v2 pre-check S0 product-source Snapshot |
| `<evidence_path>/source-after-checks.json` | Source Snapshot schema version 1을 사용하는 v2 post-check S1 product-source Snapshot |
| `<evidence_path>/run-manifest.json` | mechanical file records와 local consistency identifier; `task_id`, `run_id`, `files`, `evidence_sha256` |
| `<evidence_path>/verdict.raw.json`, `verdict.json` | recorded manual Verdict 원본과 canonical snapshot |
| `<evidence_path>/completion.json` | successful completion의 Task/Run identity와 consumed `evidence_sha256` |

새 source-bound Run에서는 `verification.json`만 schema version 2로 올라간다. Task,
changed-files, checks, Run manifest, bundle, Verdict, Completion document schema는
version 1을 유지한다. Adapter는 optional field 존재를 추측하지 말고 verification
version으로 dispatch해야 한다.

Valid verification v1 Run은 계속 읽거나 bundle을 만들고 Verdict record/show에 사용할
수 있다. Current-main `complete`는 exit 9로 거부하며 in-place upgrade하지 않는다.
v2 bundle은 S0과 S1을 포함하지만 historical artifact다. Bundle 생성은 current S2
수집, current source 비교, check 재실행, completion 판정을 하지 않는다.

`changed-files.json`, `checks.json`, check logs, `diff.patch`는 위 Run record의
Evidence로 보존되지만, 이 문서에 열거되지 않은 field나 내부 표현은 Adapter
compatibility contract가 아니다. Portable review가 필요하면 filesystem을 직접
조합하는 대신 `verifier bundle`을 사용한다.

## Unsupported dependencies

Adapter는 다음에 의존하면 안 된다.

- `src/harness` 내부 module 또는 직접 Python import
- private function, Python exception class, undocumented dataclass
- 내부 Git command 또는 subprocess 구현
- undocumented Evidence field, 임시 파일명, atomic-write 방식
- test fixture, repository-local prompt override, 개발 환경의 editable install

이 분리는 Core의 deterministic local Evidence 책임과 Adapter의 UI, model, network,
credential, retry 정책을 분리한다. Harness Core `0.2.0.dev0`은 모델 API나 외부
verifier CLI를 호출하지 않는다. `0.2.0.dev0` release artifact는 배포하지 않으며,
v0.1.1 fallback install은 S0/S1/S2 Source Binding이 없는 legacy behavior
profile이다.
