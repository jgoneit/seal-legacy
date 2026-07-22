# Harness exit codes

Language: [English](exit-codes.md) | 한국어

아래 exit code는 공개 CLI 계약이다. 이후 새 명령을 추가할 수는 있지만, 이미
정의된 숫자의 의미를 바꾸지 않는다.

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

## `harness complete` 판정

`harness complete <TASK_ID> --run-id <RUN_ID>`는 check나 Git diff를 재실행하지
않고 해당 run 디렉터리의 evidence만 읽는다. 먼저 canonical `validate_run()`이
저장 Task/Run identity, artifact path, check 결과, scope, mechanical result와
`run-manifest.json`의 raw-byte digest integrity를 확인한다. `--run-id`는 필수이며
암묵적인 latest-run 선택은 지원하지 않는다.

성공(exit 0)하려면 다음이 모두 성립해야 한다.

- 요청한 Task와 run id가 saved Task 및 `verification.json`의 identity와 일치한다.
- 필수 evidence 파일과 `verification.json`이 나열한 evidence 파일이 존재하고,
  JSON evidence는 parse 및 내부 일관성 검사를 통과한다.
- `run-manifest.json`이 expected mechanical file 목록과 정확히 일치하고, 각 파일의
  raw-byte size·SHA-256 및 canonical `evidence_sha256`이 일치한다.
- `scope_pass`가 `true`다.
- 모든 required check가 `passed=true`이며 timeout이 없다.
- `required_checks_pass=true`이고 `mechanical_result="pass"`다.
- Task의 `verifier.required`가 `true`면 유효한 manual verdict가 있고,
  그 verdict가 `pass`이며 blocker가 0개다.
- Task의 `verifier.required`가 `false`면 verdict 없이 mechanical-only로
  완료할 수 있다. 단, 기록된 verdict가 `fail` 또는 `unable`이거나 blocker를
  포함하면 exit 7로 거부한다.

필수 check 실패, timeout, Scope violation, `mechanical_result="fail"`은
`validate_run()` 자체의 오류가 아니다. 이들은 정상적으로 기록된 failed Run이며
bundle export나 Manual Verdict 기록은 가능하다. `complete`만 completion policy에
따라 exit 4, 5, 6 또는 7로 거부한다.

verdict가 기록되어 있다면 raw verdict와 normalized snapshot은 함께 존재하고 parse 및
일치 검사를 통과해야 한다. 하나만 존재하거나 둘 중 하나가 손상되면 verifier가
optional이어도 completion은 exit 8을 반환한다. 둘 다 없고 verifier가 optional이면
mechanical-only completion은 허용된다. warning과 note는 complete를 차단하지 않고
`completion.json`의 count로 남는다. 성공 completion은 소비한 mechanical Evidence
집합의 `evidence_sha256`도 기록한다.

저장 evidence가 정상적으로 읽힌 뒤에는 verifier gate(exit 7)를 먼저 판정하고,
이어서 scope(exit 4), required timeout(exit 6), required check failure(exit 5)를
판정한다. evidence 누락·손상(exit 8)은 이러한 완료 판정보다 앞서 보고된다.

`validate_run()`은 저장 파일만 대상으로 한다. 현재 working tree를 수집하거나
비교하지 않고, Git diff를 재생성하지 않으며, check를 재실행하지 않는다. manifest
mismatch는 exit 8의 evidence corruption으로 처리하고 파일을 복구하거나 rollback하지
않는다. 따라서 현재 source binding은 이 exit-code 계약의 일부가 아니다.

`harness verify`는 check 결과를 evidence로 기록하는 명령이므로, required check가
실패하거나 timeout이 나더라도 evidence 기록 자체가 성공하면 exit 0을 반환한다.
그 결과의 완료 거부는 이후 `harness complete`가 위의 exit code로 표현한다.
