Outcome Harness는 Agent가 어떻게 작업하는지 통제하지 않는다. Agent가 완료했다고 주장할 자격이 있는지를 검증하고, 그 결과를 누적한다.

## 해결하려는 문제

코딩 Agent의 완료 주장은 작업 과정의 통제와 별개로 검증 가능해야 하며, 각 작업에서 얻은 검증 결과는 이후 완료 주장에 대한 신뢰 판단을 위해 누적될 필요가 있다.

## 비목표

- Hook
- PreToolUse
- daemon
- runtime state machine
- exact-y 승인
- plan hash
- approval token
- 실행 중간 interception
- subagent topology 강제
- worktree orchestration
- Agent 내부 작업 방식 통제

## 현재 상태

experimental, Phase 1c = Task Spec snapshot, 변경 수집, check 실행, mechanical
verification 및 explicit evidence completion. independent verifier는 아직 구현되지
않았다.

Task Spec은 저장소의 `.harness/checks.json` 카탈로그를 참조하거나 인라인 check
정의를 사용할 수 있다. `harness task create --file task.json`은 현재 Git `HEAD`를
`baseline`으로 기록해 `.harness/tasks/<TASK_ID>.json`에 저장한다. 기존 id는
`--force` 없이 덮어쓰지 않는다.

## Phase 1a: 변경 수집과 Scope 판정

내부 모듈 `harness.gitdiff.collect_changes(task, cwd=..., base_ref=...)`는 Task
snapshot의 `baseline`(또는 이를 우선하는 `base_ref`)부터 현재 working tree까지의
변경 메타데이터를 메모리에서 수집한다. committed, staged, unstaged, untracked
레이어를 구분하며 rename의 이전 경로, 삭제, file mode 변경, binary 여부를 보존한다.
binary 변경은 `is_binary` 표시만 남기며 파일 내용이나 patch는 수집하지 않는다.

Scope는 문자열 prefix가 아니라 경로 구성요소 경계로 판정한다. 따라서 `src/foo`는
`src/foo/A.java`를 포함하지만 `src/foobar/A.java`는 포함하지 않는다. rename은 이전
또는 현재 경로 중 하나가 Scope에 있으면 Scope 영향으로 판정한다.

Harness 자체 기록은 수집 결과에서 관찰할 수 있지만 product diff와 Scope 판정에서는
제외한다. 제외 대상은 다음과 같다.

- `.harness/tasks/**`
- `.harness/evidence/**`
- `.harness/runs.jsonl`
- `.harness/lessons.md`
- `.harness/config.json`

## Phase 1b: check 실행과 evidence

`harness verify <TASK_ID>`는 저장된 Task Spec의 check를 정의된 순서대로 argv 배열로
실행한다. shell은 사용하지 않으며, `--base-ref <GIT_REF>`를 지정하면 이번 run에서만
snapshot `baseline` 대신 해당 Git ref를 사용한다.

각 run은 `.harness/evidence/<TASK_ID>/<RUN_ID>/`에 다음 evidence를 남긴다.

- `task.json`, `changed-files.json`, `diff.patch`, `checks.json`, `verification.json`
- check별 stdout/stderr 파일

`verification.json`은 scope와 required check 결과로 계산한 `mechanical_result`만
기록한다. 이 mechanical verification은 independent verifier, bundle, ledger를
구현하지 않는다.

## Phase 1c: 저장 evidence의 complete 판정

`harness complete <TASK_ID> --run-id <RUN_ID>`는 이미 저장된 특정 run의 evidence를
검증한다. check를 재실행하거나 Git diff를 다시 수집하지 않으며, `--run-id`가 없는
latest-run 선택도 하지 않는다.

complete는 Task/run identity, evidence 파일 존재와 JSON 무결성, `scope_pass`, 모든
required check의 pass, `required_checks_pass`, `mechanical_result="pass"`를 모두
확인한다. 성공하면 동일한
`.harness/evidence/<TASK_ID>/<RUN_ID>/completion.json`을 기록한다.

Phase 1c에는 independent verifier evidence가 없으므로 Task Spec의
`verifier.required=true`는 complete를 항상 거부한다(exit 7). 이는 requirement를
자동으로 낮추지 않는 의도된 fail-closed 동작이다. `verifier.required=false` Task는
mechanical evidence만으로 complete할 수 있다.

안정적인 CLI exit code는 [docs/exit-codes.md](docs/exit-codes.md)에 기록한다.

## Phase 2 이후

이후 Phase는 Outcome Harness 자신을 이 Harness로 검증한다. 각 Task는
`.harness/tasks/`에 저장된 Task Spec을 사용하고, 변경에 대한 mechanical evidence는
`harness verify <TASK_ID>`로 생성한다. independent verifier와 ledger는 이후 Phase의
별도 작업이며 Phase 1c의 complete가 이를 성공으로 가장하지 않는다.

> 경고: check의 stdout과 stderr는 evidence 파일에 그대로 저장된다. Harness는 secret을
> 자동으로 제거하거나 마스킹한다고 주장하지 않는다. 민감한 값을 출력하지 않는 check를
> 사용해야 한다.
