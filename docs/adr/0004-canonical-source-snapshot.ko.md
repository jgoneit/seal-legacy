# ADR 0004: 최종 product source를 canonical Snapshot으로 식별

Language: [English](0004-canonical-source-snapshot.md) | 한국어

## Status

Accepted

## Context

Harness는 Task baseline commit을 저장하고 committed, staged, unstaged,
untracked change metadata를 layer별로 수집할 수 있다. 이 layer는 Evidence에는
유용하지만 현재 Working Tree가 나타내는 최종 product source의 단일 identity는
제공하지 않는다. 같은 byte가 unstaged에서 staged로, staged에서 committed로
이동해도 source identity는 바뀌지 않아야 한다.

R1a는 이후 phase가 verification, stored Evidence, completion에 source를 binding하기
전에 계산 자체를 독립적으로 고정한다. Scope enforcement는 별도 mechanical
policy이므로 source identity에는 Task Scope 밖 product change도 포함한다.

## Decision

- `collect_source_snapshot(task, *, cwd=None)`을 유일한 read-only collection
  API로 둔다. 저장된 Task baseline만 사용하며 `--base-ref`나 다른 override를
  받지 않는다.
- baseline은 full commit object id로 resolve한다. Candidate path는 baseline의
  complete tree, baseline부터 최종 Working Tree까지의 단일 Git 비교, current
  tracked path, current non-ignored untracked path를 합친다. `assume-unchanged`,
  `skip-worktree`, `core.filemode`, clean filter 같은 Git index hint와 conversion
  setting은 source byte authority로 사용하지 않는다. 실제 지원 Working Tree
  node의 raw byte와 normalized mode를 baseline blob과 비교해 index-only 중간
  상태가 결과에 섞이지 않게 한다.
- current Git ignore rule은 untracked path를 제외한다. canonical Harness metadata
  predicate는 Task, Evidence, runs, lessons, config metadata를 제외한다. Scope 밖
  product file은 포함한다.
- Entry는 repository-relative Git path byte 순서로 정렬한다. present entry는
  normalized mode, raw-byte size, SHA-256을 기록하고 deleted entry는 mode, size,
  hash를 null로 기록한다. Rename은 old path deletion과 new path presence로
  표현한다. Directory는 entry가 아니라 container이며 지원하는 descendant
  source node만 참여한다.
- regular file은 `100644` 또는 `100755` mode를 사용하고 bounded chunk로 hash한다.
  Symlink는 `120000` mode를 사용한다. Absolute, external, broken,
  repository-relative target 모두 target을 따라가지 않고 link-target byte를
  hash한다.
- Gitlink/submodule, FIFO, socket, device와 기타 unsupported source node는
  `SourceSnapshotError`로 실패한다. Nested path를 읽을 때 static parent
  symlink를 따라가지 않는다.
- Collection은 bounded semantic observation을 두 번 수행한다. 모든 관찰된
  product-source node의 private stat fingerprint는 entry와 digest에서 제외한다.
  File identity, size, timestamp, type 또는 최종 entry가 일치하지 않으면 자동
  retry 없이 실패한다.
- `snapshot_sha256`은 schema version 1, full baseline, sorted entries만 담은
  canonical JSON을 hash한다. Serialization은 ASCII-safe escaping, sorted key,
  compact separator를 사용한다. Digest 자신은 제외하며 timestamp, absolute
  path, source file body를 넣지 않는다.

## Consequences

같은 baseline과 final source는 unstaged, staged, committed transition과 무관하게
같은 digest를 만든다. Content, path, normalized executable mode, symlink target,
binary byte가 바뀌면 Snapshot도 바뀐다. 동일한 tree를 가진 commit이라도 baseline
자체는 identity에 포함된다.

Filesystem은 transactional snapshot service가 아니다. Bounded double observation과
file descriptor 확인은 지원하는 concurrent change를 탐지하지만 hostile kernel이나
remote filesystem의 atomicity를 주장하지 않는다.

R1a는 Snapshot artifact를 저장하거나 check를 실행하지 않고, CLI output,
`validate_run()`, completion gate를 변경하지 않으며 `--base-ref`를 제거하지 않는다.
Digest는 local deterministic identifier이며 signature, remote attestation,
cryptographic provenance 또는 external trust anchor가 아니다.

## Rejected alternatives

- `HEAD`, index 또는 Git layer sequence를 source identity로 hash하는 방식
- Snapshot을 Task Scope로 제한하는 방식
- Symlink를 따라 target file content를 hash하는 방식
- Git의 `120000` blob semantics를 보존하지 않고 모든 symlink를 거부하는 방식
- Snapshot에 source file body 전체를 저장하는 방식
- 범용 repository, provider, signing, CI 또는 remote-attestation layer를 추가하는 방식
- R1a에서 verify, Evidence, `validate_run()`, bundle 또는 completion을 연결하는 방식

## R1b amendment

[ADR 0005](0005-verify-complete-source-binding.ko.md)는 이 canonical collector를
변경 없이 S0, S1, S2로 연결하고 stored verification contract를 versioning하며,
Run 단위 `--base-ref` override를 제거한다.
