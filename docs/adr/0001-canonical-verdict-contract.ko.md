# ADR 0001: Verdict Schema를 canonical contract로 사용

Language: [English](0001-canonical-verdict-contract.md) | 한국어

## Status

Accepted

## Context

Manual Verdict의 공개 JSON Schema와 verifier prompt, Python 수작업 validator가 서로 다른 구조를 정의하면 같은 Harness 버전이 환경마다 다른 Verdict를 만들거나 받아들일 수 있다. 특히 prompt가 Schema와 다른 verdict 값과 finding field를 지시하면 bundle을 검토한 사람이 정상적으로 보이는 JSON을 제출해도 runtime에서 거부될 수 있다.

Verdict는 package가 설치된 환경에서도 사용되므로 source tree의 임의 파일이나 repository별 prompt override를 runtime contract로 삼을 수 없다. 구조 validation은 반복되는 Python 조건문보다 public Schema에 의해 수행되어야 한다.

## Decision

- root의 schemas/verdict.schema.json과 prompts/verifier.md를 사람이 편집하는 canonical source로 둔다.
- src/harness/resources의 Verdict Schema와 prompt는 generated mirror이며, scripts/sync_contracts.py와 CI가 byte-for-byte 동기화를 확인한다.
- runtime은 importlib.resources로 packaged Verdict Schema를 읽고 Draft 2020-12 validator와 FormatChecker로 구조와 format을 검증한다.
- Python 수작업 구조 validator, enum 목록, exact-key 검사, timestamp format 검사를 제거한다.
- validator는 Schema 이후 특정 Task/run에 연결하기 위한 expected identity만 context validation으로 수행한다.
- verifier prompt의 완전한 JSON 예시는 실제 validator로 검증한다.
- bundle은 package resource의 verifier instruction만 사용한다. repository별 prompt override는 현재 지원하지 않는다.

## Consequences

Verdict의 field, enum, type, unknown-property policy, minimum length, date-time format은 하나의 JSON Schema에서 결정된다. runtime dependency로 jsonschema와 RFC 3339 format checker 구현을 제공해야 하며, package data에는 Schema resource도 포함되어야 한다.

record와 show의 공개 CLI 형태 및 verdict.raw.json, verdict.json 파일명은 유지한다. verdict.py는 파일 I/O, raw 보존, atomic snapshot 저장, 저장된 raw/snapshot 재검증, 의미 일치 비교, finding count 계산에 집중한다.

이 결정은 full Run integrity validator를 도입하지 않는다. Evidence manifest, digest, snapshot binding, external verifier 실행, automatic fallback, attestation은 이 ADR의 범위 밖이다.

## Rejected alternatives

- Python validator를 canonical source로 유지
- Schema를 test 전용 문서로 유지
- repository prompt를 무제한 override
- Schema와 prompt를 각각 독립적으로 관리
