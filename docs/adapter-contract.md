# Outcome Harness Adapter CLI Contract

이 문서는 Codex Plugin을 포함한 thin adapter가 Outcome Harness Core v0.1.0을
subprocess로 호출할 때의 공개 계약이다. Adapter는 Core Python package를 import하지
않고, 아래 CLI와 stdout JSON만 사용해야 한다.

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

`harness verify`는 v0.1.0에서 optional `--base-ref <GIT_REF>`도 지원한다. 이 옵션은
Task snapshot baseline을 해당 Run에 한해 override하는 알려진 한계이며, Adapter는
명시적으로 필요한 경우에만 전달해야 한다.

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
`error: <message>` 형식으로 기록하며 성공 JSON을 stdout에 섞지 않는다. argparse가
거부한 command 형태는 usage text를 stderr에 쓰고 exit `2`를 반환할 수 있다.

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

이 숫자의 기존 의미는 stable contract다. 자세한 completion 판정 순서는
[Exit codes](exit-codes.md)를 따른다.

## Public read-only artifacts

Adapter의 기본 경계는 CLI/JSON이다. Evidence를 보여주거나 archive해야 하는 경우에만,
아래의 v0.1.0 read-only artifact surface를 사용할 수 있다. Adapter는 이 파일을 만들거나
수정해서는 안 된다.

| Location | Documented purpose and fields |
| --- | --- |
| `.harness/tasks/<TASK_ID>.json` | Task snapshot; `task create`/`task show`와 같은 Task JSON fields |
| `<evidence_path>/verification.json` | Run identity와 mechanical outcome; `task_id`, `run_id`, `baseline`, `scope_pass`, `required_checks_pass`, `mechanical_result`, `evidence_files` |
| `<evidence_path>/run-manifest.json` | mechanical file records와 local consistency identifier; `task_id`, `run_id`, `files`, `evidence_sha256` |
| `<evidence_path>/verdict.raw.json`, `verdict.json` | recorded manual Verdict 원본과 canonical snapshot |
| `<evidence_path>/completion.json` | successful completion의 Task/Run identity와 consumed `evidence_sha256` |

`changed-files.json`, `checks.json`, check logs, `diff.patch`는 위 Run record의 evidence로
보존되지만, 이 문서에 열거되지 않은 field나 내부 표현은 Adapter compatibility contract가
아니다. portable review가 필요하면 filesystem을 직접 조합하는 대신 `verifier bundle`을
사용한다.

## Unsupported dependencies

Adapter는 다음에 의존하면 안 된다.

- `src/harness` 내부 module 또는 직접 Python import
- private function, Python exception class, undocumented dataclass
- 내부 Git command 또는 subprocess 구현
- undocumented Evidence field, 임시 파일명, atomic-write 방식
- test fixture, repository-local prompt override, 개발 환경의 editable install

이 분리는 Core의 deterministic local Evidence 책임과 Adapter의 UI, model, network,
credential, retry 정책을 분리한다. v0.1.0 Core는 모델 API나 외부 verifier CLI를 호출하지
않는다.
