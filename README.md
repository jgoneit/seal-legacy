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

experimental, Phase 1 = Task Spec의 파싱·검증·snapshot 저장

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

이 단계는 CLI를 노출하지 않으며 Task check 실행, evidence 파일 생성,
`verification.json`, complete 처리를 수행하지 않는다.
