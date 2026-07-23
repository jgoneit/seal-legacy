# Harness repository instructions

## Core boundaries

- 이 지침은 저장소 전체의 Core 변경과 테스트에 적용한다.
- 기능 추가 전에 관련 Core 전체의 책임 경계와 호출 흐름을 확인한다.
- 전체 구조를 조사하되 전체 저장소를 자동으로 전면 리팩터링하지 않는다.
- 현재 변경의 dependency cone 안의 중복 구현과 dead code만 삭제한다.
- 기존 대형 모듈에 새 책임을 계속 누적하지 않는다.
- `validate_run()`의 저장 Run integrity public authority는 하나로 유지한다.
- 같은 계약을 둘 이상의 모듈에서 독립적으로 재구현하지 않는다.
- bundle, complete, verdict는 저장 Evidence를 각자 재해석하지 않는다.
- 새 책임은 실제 경계와 소비자가 확인될 때만 분리한다.

## Contract preservation

- CLI command, stdout JSON, stderr, exit code의 의미를 보존한다.
- Task, Evidence, Verdict, bundle Schema의 공개 의미를 보존한다.
- failed check, timeout, scope violation을 corrupt Evidence와 구분한다.
- bundle은 저장 Run을 재실행하지 않는다.
- current-source binding이 없는 동안 이를 제공한다고 주장하지 않는다.
- runtime dependency는 명시적 설계 근거 없이 추가하지 않는다.

## Change protocol

- 구조 변경 전에 해당 public behavior의 Characterization Test를 추가한다.
- 기존 테스트가 계약을 보호하면 중복 테스트를 만들지 않는다.
- 정상 경로뿐 아니라 identity, path, digest, failure 경계를 보호한다.
- 중복을 제거할 때 canonical implementation을 먼저 지정한다.
- 미래용 service, registry, provider, repository abstraction을 만들지 않는다.
- 관련 없는 구조 문제는 audit에 기록하고 이번 변경에서 수정하지 않는다.
- 기존 dirty change를 보존하고 관련 변경과 섞지 않는다.
- 줄 수 감소만을 위한 기계적 파일 분할을 하지 않는다.

## Verification

- 변경 중에는 관련 테스트를 먼저 실행한다.
- 완료 전에는 전체 unittest suite를 실행한다.
- `python3 scripts/sync_contracts.py --check`를 실행한다.
- wheel을 빌드해 package contents를 확인한다.
- clean environment에서 CLI, public imports, packaged resources를 smoke-test한다.
- `git diff --check`를 실행하고 미실행 검증과 남은 리스크를 명시한다.

## Agent coordination

- 필요할 경우 Codex가 SubAgent 사용 여부와 수를 판단한다.
- 고정 Agent 역할, 수, 순서, topology를 강제하지 않는다.
- 독립적인 read-heavy 조사와 테스트 분석을 우선 위임한다.
- Main Agent가 최종 쓰기, 통합, 검증 책임을 가진다.

## Documentation

- authority나 책임 경계가 바뀌면 architecture와 ADR을 함께 검토한다.
- stable exit code와 adapter contract의 drift를 확인한다.
- superseded 문서는 historical 상태를 명확히 유지한다.
- 알려진 한계와 source-binding 부재를 숨기지 않는다.
- public Markdown은 English와 Korean 쌍 및 reciprocal link를 유지한다.
- 구현되지 않은 기능을 현재 계약으로 문서화하지 않는다.
