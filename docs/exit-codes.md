# Outcome Harness exit codes

Phase 1c부터 아래 exit code는 공개 CLI 계약이다. 이후 Phase에서 새 명령을
추가할 수는 있지만, 이미 정의된 숫자의 의미를 바꾸지 않는다.

| Code | Meaning | Typical condition |
| ---: | --- | --- |
| 0 | success | 요청한 명령이 성공적으로 끝났고, `complete`의 모든 완료 조건을 만족함 |
| 2 | invalid input or schema | 잘못된 CLI 인자, Task/run 불일치, 유효하지 않은 Task Spec 또는 saved Task 구조 |
| 3 | git/repository error | Git 실행 실패, Git 저장소 밖에서의 실행, 해석할 수 없는 Git baseline |
| 4 | scope violation | 저장된 evidence가 product Scope 밖의 변경을 기록함 |
| 5 | required check failure | timeout이 아닌 required check 실패가 저장되어 있음 |
| 6 | timeout | required check timeout이 저장되어 있음 |
| 7 | required verifier evidence missing | Task가 independent verifier evidence를 요구하지만 해당 evidence가 없음 |
| 8 | evidence missing or corrupt | 필요한 evidence 파일이 없거나, JSON을 읽을 수 없거나, 저장된 record가 서로 모순됨 |

## `harness complete` 판정

`harness complete <TASK_ID> --run-id <RUN_ID>`는 check나 Git diff를 재실행하지
않고 해당 run 디렉터리의 evidence만 읽는다. `--run-id`는 필수이며 암묵적인
latest-run 선택은 지원하지 않는다.

성공(exit 0)하려면 다음이 모두 성립해야 한다.

- 요청한 Task와 run id가 saved Task 및 `verification.json`의 identity와 일치한다.
- 필수 evidence 파일과 `verification.json`이 나열한 evidence 파일이 존재하고,
  JSON evidence는 parse 및 내부 일관성 검사를 통과한다.
- `scope_pass`가 `true`다.
- 모든 required check가 `passed=true`이며 timeout이 없다.
- `required_checks_pass=true`이고 `mechanical_result="pass"`다.
- Task의 `verifier.required`가 `false`다.

Phase 1c에는 independent verifier evidence 형식이나 runner가 없다. 그러므로
`verifier.required=true`인 Task는 mechanical evidence가 통과했더라도 항상
exit 7로 complete를 거부한다. 이 동작은 verifier requirement를 자동으로 무시하는
fallback이 아니라 fail-closed 계약이다.

저장 evidence가 정상적으로 읽힌 뒤에는 required verifier 누락(exit 7)을 먼저
판정하고, 이어서 scope(exit 4), required timeout(exit 6), required check
failure(exit 5)를 판정한다. evidence 누락·손상(exit 8)은 이러한 완료 판정보다
앞서 보고된다.

`harness verify`는 check 결과를 evidence로 기록하는 명령이므로, required check가
실패하거나 timeout이 나더라도 evidence 기록 자체가 성공하면 exit 0을 반환한다.
그 결과의 완료 거부는 이후 `harness complete`가 위의 exit code로 표현한다.
