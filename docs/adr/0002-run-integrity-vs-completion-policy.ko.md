# ADR 0002: Run integrity와 completion policy 분리

Language: [English](0002-run-integrity-vs-completion-policy.md) | 한국어

## Status

Accepted

## Context

Phase 1의 completion과 verifier bundle은 저장된 Task/Run Evidence를 각각 다시
읽고 일부 consistency를 독자적으로 검사했다. 이 구조에서는 동일한 Run이 명령마다
다르게 받아들여질 수 있고, check 결과·scope 결과·Evidence path 검증의 수정 지점도
분산된다.

또한 실패한 작업 결과와 손상된 Evidence는 다른 상태다. required check가 실패하거나
timeout이 발생하고 Scope violation이 기록되어도, 해당 Run은 당시 결과를 정확하게
보존한 정상 Evidence일 수 있다. 반대로 `passed=true`와 non-zero exit code처럼
내부 자료가 모순되면 completion policy를 판단하기 전에 Run을 신뢰할 수 없다.

## Decision

- `harness.run_validator.validate_run(task_id, run_id, cwd=...)`를 저장 Run integrity의
  canonical 진입점으로 둔다.
- validator는 saved Task snapshot, Run `task.json`, `changed-files.json`, `diff.patch`,
  `checks.json`, `verification.json`, check log의 존재·readability·identity·상호
  consistency를 확인하고 immutable `ValidatedRun`을 반환한다.
- validator는 Evidence path traversal, absolute path, duplicate path, Run directory 밖
  symlink escape를 거부한다.
- validator는 failed check, timeout, Scope violation, `mechanical_result="fail"`을
  corruption으로 취급하지 않는다. 구조가 일관적이면 failed Run도 `ValidatedRun`이다.
- `evidence.complete_task`, `bundle.create_verification_bundle`, `verdict.record_verdict`,
  `verdict.show_verdict`는 각각의 정책을 적용하기 전에 동일한 `ValidatedRun`을 사용한다.
- completion은 Scope, required check, timeout, Manual Verdict와 blocker 조건만 추가로
  평가한다. bundle은 portability와 output safety만, Verdict 경로는 Manual Verdict
  contract와 raw/snapshot preservation만 담당한다.
- validator는 Git diff 재수집, check 재실행, current source 비교, 모델 API·외부 CLI
  호출, Agent runtime hook·approval·state machine을 수행하지 않는다.

## Consequences

저장 Evidence가 손상되면 consumer마다 같은 canonical error boundary에서 거부된다.
반대로 mechanical fail Run도 external review bundle과 독립 Manual Verdict의 입력으로
보존된다. 공개 CLI 명령과 기존 exit-code 숫자는 바꾸지 않으며, `complete`만 valid
Run에 대한 completion policy를 exit 4~7로 표현한다.

이 결정은 local filesystem을 immutable storage로 만들지 않는다. 이후 ADR 0003이
mechanical Evidence manifest와 digest를 추가해 파일 수정·누락을 탐지하지만, 동일한
로컬 사용자가 Evidence와 manifest를 함께 다시 계산하는 공격, diff와 changed-files의
의미적 binding, verification 시점 source와 현재 source의 binding은 여전히 해결하지
않는다.

## Rejected alternatives

- completion, bundle, Verdict 경로가 각자 Evidence consistency를 다시 검사하는 방식
- mechanical failure를 즉시 corrupt Evidence로 취급하는 방식
- validator에서 Git diff를 재생성하거나 check를 재실행하는 방식
- validator에 source snapshot, external verifier adapter, automatic repair를 함께 추가하는 방식
