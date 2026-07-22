# ADR 0000: Outcome Over Process (historical)

Language: [English](0000-outcome-over-process.md) | 한국어

Status: Superseded
Date: 2026-07-16

> Historical design note: this document records an earlier direction and does
> not describe the current shipped contract. In particular, its references to
> cross-vendor execution, runs.jsonl, trust summaries, and alternative Verdict
> states are not implemented. See the README, architecture document, and
> ADR 0001 for the current supported surface.

## Context

이전 Harness는 약 3,100줄의 Python guard와 약 1,850줄의 테스트로 구성되어 있었다. 승인 토큰, Plan hash, 정확한 `y` 응답, attestation, root-only write, `PreToolUse` hook은 각각 임의로 덧붙인 장치가 아니었다. Agent의 모든 행동이 승인된 계획과 현재 runtime state에 맞는지를 행동 전에 판정하려면, 각 장치가 서로의 상태와 예외·복구 경로를 알아야 했기 때문에 필요해진 장치들이었다. 하나의 턴을 통과시키기 위해서는 입력 형식, 승인 이력, hash, 쓰기 경계, 역할, hook 전달 경로가 모두 일관되어야 했다.

문제는 단지 구현이 복잡해졌다는 데 있지 않다. 과정 게이트는 모델의 모든 턴과 충돌한다. 작업이 길어져 턴 수가 늘수록 정상적인 탐색, 설명, 도구 호출, 수정, 재검토가 gate와 만나는 횟수도 늘어난다. 따라서 마찰과 false block의 비용은 작업량에 비례해 누적된다. 더 성능 좋은 모델은 의도 파악, 계획 준수, 도구 사용을 더 잘하게 되지만, 과거의 행동 패턴을 전제로 한 gate의 가치는 그만큼 감가상각된다. 반대로 gate의 상태 불일치나 설치·hook 경로 문제는 모델의 실제 작업 품질과 관계없이 작업을 멈춘다.

결과 검증은 반대 특성을 가진다. Agent가 내부적으로 어떤 순서로 생각하고 도구를 썼는지 대신, 완료를 주장하는 시점에 Task Spec의 scope와 definition of done을 만족하는 증거가 있는지를 본다. 검증 비용은 모든 턴이 아니라 완료 주장과 그 증거 묶음에 결합된다. 모델과 검증기가 좋아질수록 더 좋은 증거를 만들고 더 잘 반증할 수 있으므로, 이 통제는 모델 성능 향상과 경쟁하기보다 이를 활용한다.

## Decision

통제를 제거하지 않고 위치를 옮긴다. Harness는 행동을 차단하지 않는다. Agent는 자신의 작업 방식을 선택하고 수행할 수 있다. 다만 scope, definition of done, evidence, independent review에 비추어 검증된 결과만 완료로 주장할 수 있다. 행동 차단에서 완료 차단으로 바꾸는 것이다.

남기는 유일한 fail-closed 규칙은 다음과 같다. **검증되지 않은 결과는 완료가 아니다.** 필요한 증거가 없거나, evidence와 Task Spec의 연결을 검토할 수 없거나, independent review가 수행되지 않았다면 결과는 `complete`가 아니라 `unverified`, `inconclusive`, 또는 `failed`로 기록한다. 이 규칙은 Agent의 다음 행동을 금지하지 않지만, 근거 없는 성공 주장을 성공으로 누적하지 않는다.

Scope는 무엇을 검증해야 하는지를 정의하는 경계로 유지한다. Definition of done은 성공을 판정할 수 있는 관찰 가능한 조건으로 유지한다. Evidence는 명령 출력, diff, 테스트 결과, 검토 기록처럼 그 조건을 뒷받침하는 원자료와 출처로 유지한다. Independent review는 실행자가 낸 증거와 결론을 별도 관점에서 반증하는 절차로 유지한다. 이 네 가지는 완료 판정에 필요하지만, 특정 runtime, 역할 수, 하위 Agent 구성, 승인 문구를 강제하지 않는다.

따라서 runtime gate, approval state machine, Plan hash authority, hook 기반 enforcement, mandatory topology, worktree orchestration은 새 Harness의 개념 모델에서 제거한다. 승인 토큰이나 상태 전이는 행동의 권한을 증명하지 않으며, hook은 정상 작업을 중간에서 가로채지 않는다. 독립 검토는 유지하되 이를 특정 subagent topology나 root-only writer 규칙으로 구현하지 않는다.

### Cross-vendor verification

Cross-vendor verification은 검증 중인 가설이자 기본 설정이다. 기본적으로 실행 Agent와 다른 vendor의 verifier를 선택해 상관된 오류를 줄이고자 하지만, 이것이 이미 더 정확하거나 독립적이라는 검증된 사실은 아니다. W1의 현재 실측은 표본 1건에서 정탐 1건, 오탐 0건이다. 이 결과는 단일 사례의 관측일 뿐이며, 정확도·일반화 가능성·vendor 독립성을 증명하지 않는다.

검증 기록에는 verifier의 vendor와 수행 방식이 남아야 한다. 다른 vendor를 사용할 수 없었을 때 같은 vendor 또는 사람이 수행한 검토를 숨기거나 cross-vendor로 표기하지 않는다. 그 구분 자체가 이후 가설을 검증할 데이터가 된다.

### Run record와 trust summary

`runs.jsonl`이 source of truth다. 각 run은 Task Spec, evidence, verifier provenance, verdict, 그리고 나중의 정정 또는 supersession을 append-only 기록으로 남긴다. trust summary는 이 기록에서 다시 계산하는 derived view이며, 계산식이나 표본 범위가 바뀌어도 원자료를 보존한 채 재생성할 수 있어야 한다.

직접 수정되는 `trust.json`은 만들지 않는다. 사람이 설명을 고치거나 현재 신뢰도를 바꾸기 위해 summary 파일을 편집할 수 있다면, 그 파일은 관측값과 판단을 섞은 두 번째 source of truth가 된다. 정정은 `runs.jsonl`에 근거와 함께 새 기록으로 남기고, summary는 그 결과를 반영한다.

### Task Spec 저작 주체

Task Spec의 저작 주체는 작업을 요청하고 결과에 책임지는 사람이다. 요청자는 목적, scope, definition of done을 작성하거나 명시적으로 채택한다. 실행 Agent는 이를 구조화하거나 초안을 제안할 수 있지만, 자신의 완료를 판단할 기준을 단독으로 만들 수 없다. 그렇지 않으면 실행자가 난이도를 낮춘 spec과 그 spec을 만족했다는 evidence를 동시에 만들 수 있어 결과 검증의 독립성이 무너진다.

이 결정은 이전의 exact-`y` 승인이나 Plan hash authority를 되살리지 않는다. Task Spec의 저작·채택은 행동을 허용하는 runtime gate가 아니라, 나중에 완료 주장을 평가할 때 사용하는 입력의 출처를 명확히 하는 일이다. 충분한 Task Spec이 없으면 Agent는 작업할 수는 있어도 정확한 완료 주장을 할 수 없다.

## Consequences

새 설계는 과정 통제 코드, state 복구, hook 호환성, 설치 경로와 topology에 묶인 테스트 표면을 크게 줄인다. Agent는 정상적인 작업을 위해 protocol을 매 턴 재현할 필요가 없고, 실패는 행동 전의 권한 오류보다 완료 시점의 증거 부족으로 드러난다. 이로써 모델과 도구가 바뀌어도 핵심 계약은 “무엇이 완료인가”와 “그 근거는 무엇인가”에 머문다.

대신 예방적 통제는 약해진다. 범위를 벗어난 행동, 위험한 도구 사용, 늦게 발견한 요구사항 해석 오류를 runtime gate가 미리 막아 주지 않는다. 빈약하거나 모호한 Task Spec은 사후 검증도 모호하게 만들며, evidence를 선택적으로 제시하거나 verifier가 같은 오류를 공유할 위험도 있다. 검증 실패가 완료 직전에 발견되면 이미 수행한 작업 일부가 낭비될 수 있다. 이 위험은 보안·권한·sandbox 같은 외부 통제를 대체하지 않는다는 점과, evidence provenance 및 independent review를 남긴다는 점으로 관리한다.

Trust data도 초기에 정책을 자동으로 결정해서는 안 된다. 표본이 적은 상태에서 trust summary가 verifier 생략, review 강도 완화, Agent 자율성 확대 같은 정책을 결정하면 관측 노이즈가 자율성을 결정하게 된다. W1의 정탐 1건·오탐 0건은 유망한 출발점일 수는 있어도 정책 임계값이 아니다. 충분한 표본 수, 작업 유형별 분포, 오탐·미탐 분석, 그리고 별도의 calibration 결정이 생기기 전까지 trust summary는 설명용 derived view로만 사용하며, fail-closed completion을 완화하지 않는다.

이 ADR은 결과 검증이 모든 종류의 실패를 잡는다고 주장하지 않는다. 대신 Agent의 작업 방식을 예측해 통제하려는 비용보다, 완료 주장에 반증 가능한 증거를 요구하고 그 기록으로 검증 방식을 개선하는 비용을 선택한다.
