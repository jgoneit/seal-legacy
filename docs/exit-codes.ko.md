# Harness exit codes

Language: [English](exit-codes.md) | 한국어

아래 exit code는 unreleased current main `0.2.0.dev0`의 공개 CLI 계약이다.
v0.1.1은 최신 published release이며 exit 0과 2–8을 정의하지만 source-bound
exit 9는 제공하지 않는다. 이후 새 명령을 추가할 수는 있지만 이미 정의된 숫자의
의미를 바꾸지 않는다.

| Code | Meaning | Typical condition |
| ---: | --- | --- |
| 0 | success | 요청한 명령이 성공적으로 끝났고, `complete`의 모든 완료 조건을 만족함 |
| 2 | invalid input or schema | 잘못된 CLI 인자, Task/run 불일치, 유효하지 않은 Task Spec 또는 saved Task 구조 |
| 3 | git/repository error | Git 실행 실패, Git 저장소 밖에서의 실행, 해석할 수 없는 Git baseline |
| 4 | scope violation | 저장된 evidence가 product Scope 밖의 변경을 기록함 |
| 5 | required check failure | timeout이 아닌 required check 실패가 저장되어 있음 |
| 6 | timeout | required check timeout이 저장되어 있음 |
| 7 | verifier gate not satisfied | required verifier evidence가 없거나, 기록된 verdict가 fail/unable이거나 blocker를 포함함 |
| 8 | evidence missing or corrupt | 필요한 evidence 파일이 없거나, JSON을 읽을 수 없거나, 저장된 record가 서로 모순됨 |
| 9 | source binding not satisfied | Run이 legacy v1이거나, check가 product source를 바꿨거나, current product source가 post-check Snapshot과 다름 |

## `harness complete` 판정

`harness complete <TASK_ID> --run-id <RUN_ID>`는 check나 Git diff를 재실행하지
않는다. 먼저 canonical `validate_run()`이 저장 Task/Run identity, artifact path,
check 결과, scope, mechanical result, versioned Source Snapshot Evidence,
`run-manifest.json`의 raw-byte digest integrity만 확인한다. Completion은 stored
Evidence와 기록된 Verdict의 integrity validation 뒤 현재 product-source Snapshot을
별도로 수집한다. `--run-id`는 필수이며 암묵적인 latest-run 선택은 지원하지 않는다.

성공(exit 0)하려면 다음이 모두 성립해야 한다.

- 요청한 Task와 run id가 saved Task 및 `verification.json`의 identity와 일치한다.
- 필수 evidence 파일과 `verification.json`이 나열한 evidence 파일이 존재하고,
  JSON evidence는 parse 및 내부 일관성 검사를 통과한다.
- `run-manifest.json`이 expected mechanical file 목록과 정확히 일치하고, 각 파일의
  raw-byte size·SHA-256 및 canonical `evidence_sha256`이 일치한다.
- `verification.json`이 version 2이고 두 Snapshot file이 valid schema-version-1
  document이며 baseline과 digest가 Task 및 verification record와 일치한다.
- Pre-check S0과 post-check S1 Snapshot이 같아
  `source_stable_during_checks=true`다.
- Current completion-time S2 Snapshot이 S1과 같다.
- `scope_pass`가 `true`다.
- 모든 required check가 `passed=true`이며 timeout이 없다.
- `required_checks_pass=true`이고 source stability까지 포함한 v2
  `mechanical_result="pass"`다.
- Task의 `verifier.required`가 `true`면 유효한 manual verdict가 있고,
  그 verdict가 `pass`이며 blocker가 0개다.
- Task의 `verifier.required`가 `false`면 verdict 없이 mechanical-only로
  완료할 수 있다. 단, 기록된 verdict가 `fail` 또는 `unable`이거나 blocker를
  포함하면 exit 7로 거부한다.

Required-check failure, timeout, Scope violation, source instability,
`mechanical_result="fail"`은 `validate_run()` 자체의 오류가 아니다. 이들은
정상적으로 기록된 failed Run이며 bundle export나 Manual Verdict 기록은 가능하다.
`complete`만 completion policy에 따라 exit 4–7 또는 9로 거부한다.

verdict가 기록되어 있다면 raw verdict와 normalized snapshot은 함께 존재하고 parse 및
일치 검사를 통과해야 한다. 하나만 존재하거나 둘 중 하나가 손상되면 verifier가
optional이어도 completion은 exit 8을 반환한다. 둘 다 없고 verifier가 optional이면
mechanical-only completion은 허용된다. warning과 note는 complete를 차단하지 않고
`completion.json`의 count로 남는다. 성공 completion은 소비한 mechanical Evidence
집합의 `evidence_sha256`도 기록한다.

실패한 completion은 `completion.json`을 만들거나 덮어쓰지 않는다. 이전 successful
completion record가 이미 있으면 이후 거부는 그 historical record를 그대로 두지만,
그 record가 current source를 eligible하게 만들지는 않는다.

Fail-closed 판정 순서는 다음과 같다.

1. v2 Snapshot Evidence를 포함한 mechanical Evidence 누락·손상·모순은 exit 8이다.
2. 기록된 Verdict Evidence 누락·손상·모순은 exit 8이다.
3. v2 Run에서 current repository의 S2를 수집하지 못하면 exit 3이다.
4. Legacy v1 Run, S0/S1 instability, S1/S2 mismatch는 exit 9다.
5. Verifier gate 미충족은 exit 7이다.
6. Scope violation은 exit 4다.
7. Required timeout은 exit 6이다.
8. Timeout이 아닌 required-check failure는 exit 5다.

Valid v1 Run은 계속 `validate_run()`, bundle export, Verdict record/show에 사용할 수
있지만 current-source-bound completion은 만족할 수 없다. Stored Evidence와 기록된
Verdict integrity 확인 뒤 exit 9를 반환한다. 자동 upgrade하지 않으며 새 v2
verification Run을 생성해야 한다. v1 completion path는 S2를 수집하지 않는다.

`validate_run()`은 계속 저장 파일만 대상으로 한다. 현재 Working Tree를 수집하거나
비교하지 않고, Git diff를 재생성하지 않으며, check를 재실행하지 않는다. Current
S2 collection은 completion-time Source Binding 경계만 담당한다. Manifest mismatch는
exit 8의 Evidence corruption으로 처리하고 파일을 복구하거나 rollback하지 않는다.
S1/S2 identity mismatch는 valid Evidence의 unsatisfied binding이므로 exit 9다.

`harness verify`는 check와 Source Snapshot 결과를 Evidence로 기록하는 명령이므로,
required check가 실패하거나 timeout이 나거나 product source를 바꿔도 Evidence 기록
자체가 성공하면 exit 0을 반환한다. S0 또는 S1 collection failure는 valid manifest나
성공 stdout result를 만들지 않는다. 그 결과의 완료 거부는 이후
`harness complete`가 위 exit code로 표현한다.

Source Binding은 bounded observation이다. Exit 0은 `complete`가 S2를 수집한 시점에
validated post-check S1과 같았다는 뜻이며, Harness가 filesystem을 lock하거나 그 관찰
뒤 또는 command 반환 뒤에도 source가 바뀌지 않는다고 보장한다는 뜻은 아니다.
