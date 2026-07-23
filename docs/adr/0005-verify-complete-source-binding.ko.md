# ADR 0005: Completion을 검증된 product source에 binding

Language: [English](0005-verify-complete-source-binding.md) | 한국어

## Status

Accepted

## Context

ADR 0004는 저장된 Task baseline 대비 final product source의 canonical identity를
정의했지만, R1a는 이 identity를 Evidence에 저장하거나 completion 시점에 비교하지
않았다. 따라서 한 source state에서 수행한 check를 설명하는 Run을 product source가
바뀐 뒤에도 `complete`가 받아들일 수 있었다. Run 단위 `verify --base-ref`
override는 verification baseline이 Task에 저장된 baseline과 달라지는 것도
허용했다.

Source binding은 stored Run integrity와 current-source policy의 기존 분리를
보존해야 한다. Historical Run은 계속 검토할 수 있어야 하며 bundle과 Verdict
operation이 current Working Tree의 authority가 되어서는 안 된다.

## Decision

- `verify --base-ref`와 그 Python API 경로를 제거한다. Verification과 Source
  Snapshot은 Task에 저장된 full commit SHA만 baseline으로 사용한다.
- 새 verification Run은 `verification.json` schema version 2를 사용한다. Task,
  changed-files, checks, manifest, bundle, Verdict, Completion document schema는
  version 1을 유지하며, 각 Source Snapshot document도 Snapshot schema version
  1을 사용한다.
- `verify`는 check 직전에 S0을, 모든 check 종료 직후 S1을 유일한 live
  collection API인 `collect_source_snapshot()`으로 수집한다. Required 또는
  optional check의 실패와 timeout도 collection이 가능하면 S1을 생략하지 않는다.
- Run은 S0을 `source-before-checks.json`, S1을
  `source-after-checks.json`으로 저장한다. 두 raw file 모두
  `run-manifest.json`의 integrity 대상이다.
- `verification.json` v2는 `source_snapshot_schema_version`,
  `source_before_checks_sha256`, `source_after_checks_sha256`,
  `source_stable_during_checks`를 기록한다. `source_stable_during_checks`는
  정확히 S0과 S1이 같을 때만 true이며, mechanical result는 scope pass,
  required-check pass, source stability로 다시 계산한다.
- S0 collection failure는 check와 Run directory 생성 전에 발생한다. S1 또는
  이후 persistence가 실패하면 valid manifest나 성공 stdout result를 만들지
  않는다. 진단을 위해 incomplete UUID directory와 이미 기록된 log가 남을 수
  있다.
- `validate_run()`은 persisted Run integrity의 유일한 public authority로 남고
  current Working Tree를 읽지 않는다. Version별 validator가 저장 Snapshot
  document, baseline, digest, stability flag, aggregate result, manifest record를
  parse하고 교차 검증한다.
- `complete`는 persisted Evidence와 기록된 Verdict의 integrity를 검증한 뒤 별도
  current-source 단계를 수행한다. v2 Run에서는 `collect_source_snapshot()`으로
  S2를 수집해 verifier, scope, timeout, required-check policy보다 먼저
  S0 = S1 = S2를 요구한다. S2는 저장하지 않는다.
- Structurally valid legacy v1 Run, S0/S1 instability, S1/S2 mismatch는 exit 9로
  completion을 거부한다. Stored Evidence corruption은 exit 8, current Snapshot
  collection 실패는 exit 3이다. 이후 우선순위는 verifier 7, scope 4, required
  timeout 6, required-check failure 5다.
- v1 Run은 계속 `validate_run()`, bundle export, Verdict record/show의 valid
  input이며 former override로 baseline을 기록한 historical Run도 포함한다. v1
  completion path는 S2를 수집하지 않는다. In-place upgrade하지 않으며
  source-bound completion 대상이 되려면 다시 verify해야 한다.
- Bundle은 v2 Run의 persisted S0과 S1을 포함하지만 S2 수집, check 재실행,
  current source 비교, completion 판정을 하지 않는다.

## Consequences

Check가 product source를 생성·수정·삭제·rename하거나 executable mode를 바꾸면
S0과 S1이 달라지고, Evidence persistence가 성공한 경우 structurally valid failed
Run으로 남는다. Gitignored untracked file과 canonical Harness metadata는 Snapshot
identity 밖에 계속 둔다.

Verification 뒤 content, path, mode, symlink target, binary byte가 바뀌어 S2가
S1과 달라지면 completion을 막는다. Unstaged, staged, committed 상태 사이에서
동일한 final source를 이동하는 것은 identity를 바꾸지 않으며, 정확한 S1 source로
복원하면 다시 binding 대상이 될 수 있다.

이것은 transactional filesystem snapshot이 아니라 bounded local observation이다.
ADR 0004가 정의한 supported race는 탐지할 수 있지만 S2 관찰 뒤 또는 `complete`
반환 뒤 source가 바뀌는 것을 막지 않는다. 또한 signature, remote attestation,
immutable ledger나 동일한 local user가 Evidence와 manifest 전체를 다시 쓰는
공격에 대한 방어가 아니다.

이 결정은 Task revision, CI pull-request base/head semantics, automatic formatter
또는 code-generation allowance, check 재실행, source rollback, external verifier
API, release를 추가하지 않는다.

## Rejected alternatives

- Source Binding field를 `verification.json` version 1에 조용히 추가하는 방식
- `validate_run()`이 current Working Tree를 읽게 하는 방식
- bundle 또는 Verdict command가 current-source equality를 강제하는 방식
- `--base-ref`를 deprecated option, hidden alias 또는 environment fallback으로
  남기는 방식
- 선택한 product-source path의 check 변경을 자동 허용하는 방식
- Completion을 immutable point in time인 것처럼 S2를 저장하거나 attest하는 방식
