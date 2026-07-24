# ADR 0003: Mechanical Evidence를 versioned Run manifest로 식별

Language: [English](0003-run-evidence-manifest.md) | 한국어

## Status

Accepted

## Context

Run integrity validator는 저장된 Task, check result, scope, path 관계가 서로 일관적인지
확인한다. 그러나 JSON whitespace, log output, binary diff처럼 의미 구조만으로는
확인되지 않는 raw-byte 변경이나 파일 교체를 명시적으로 식별하지는 못했다.

Verifier Verdict와 completion은 verify 이후 별도 명령으로 생성된다. 이 파일들을
verify 시점의 mechanical Evidence identity에 섞으면 순환 hash나 시간 순서가 다른
contract가 생긴다.

## Decision

- 각 새 Run은 verify가 `verification.json`을 저장한 뒤 마지막 단계에서
  `run-manifest.json`을 저장한다.
- manifest에는 `task.json`, `changed-files.json`, `diff.patch`, `checks.json`,
  `verification.json`, 그리고 recorded check가 참조하는 모든 stdout/stderr log만 넣는다.
- manifest 자신, `verdict.raw.json`, `verdict.json`, `completion.json`은 넣지 않는다.
- file record는 relative POSIX path 기준 ascending order이며, 각 record는 raw-byte
  `size_bytes`와 SHA-256을 가진다. Text normalization은 하지 않는다.
- `evidence_sha256`은 schema version, Task id, Run id, sorted file records만을
  UTF-8·`ensure_ascii=False`·sorted key·compact separator의 canonical JSON으로
  직렬화해 계산한다. `created_at`은 digest에서 제외한다.
- `validate_run()`은 expected mechanical file list, file record, actual raw byte size,
  file SHA-256, `evidence_sha256`을 모두 비교한다. manifest가 없는 이전 Run은
  legacy/incomplete Evidence로 거부하며 사용자는 새 verify Run을 만든다.
- bundle은 validated Run의 digest를 다시 계산하지 않고
  `source_evidence_sha256`으로 기록한다. successful completion은 동일 값을
  `evidence_sha256`으로 기록한다.

## Consequences

bundle, Verdict record/show, complete는 기존 canonical validator를 통하므로 같은
manifest mismatch를 일관되게 거부한다. Required check failure, timeout, Scope violation은
manifest가 정확하면 정상적으로 저장된 failed Run이며 external review의 입력으로 남는다.

manifest는 local consistency identifier다. signature, remote attestation, immutable
storage, completion authority 또는 external trust anchor가 아니다. 동일한 로컬 사용자가
Evidence와 manifest 전체를 재작성하는 공격은 막지 못한다. mismatch를 만나도 Harness는
source나 Evidence를 자동 복구·rollback하지 않는다.

## Rejected alternatives

- Verdict와 Completion까지 하나의 manifest에 넣어 순환 hash와 시간 순서 문제를 만드는 방식
- JSON parsing 결과나 normalized text만 hash하는 방식
- manifest 자체의 self-hash 또는 signature를 이번 local contract에 추가하는 방식
- manifest mismatch에서 자동 repair, source rollback, runtime hook·approval·monitoring을 추가하는 방식
- current source snapshot binding을 같은 Phase에 함께 도입하는 방식

## R1b amendment

[ADR 0005](0005-verify-complete-source-binding.ko.md)는 verification v2 Run의
raw-byte manifest 대상에 persisted Source Snapshot document 두 개를 추가한다.
Manifest, Verdict, Completion document schema는 version 1을 유지한다.
