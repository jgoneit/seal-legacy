# Outcome Harness v0.1.0 Release Scope

Language: [English](release-scope-v0.1.0.md) | 한국어

## Status

v0.1.0은 Outcome Harness의 첫 Experimental release다. 이 버전은 로컬에서
Evidence Run의 일관성과 completion 조건을 검증하는 CLI를 제공한다. production
enforcement, cryptographic trust, 또는 Agent 작업 과정의 통제를 주장하지 않는다.

GitHub Release는 `v0.1.0` tag가 push된 경우에만 생성된다. 일반 `main` push와 이
문서의 추가만으로 release가 발행되지는 않는다.

## Included

- Task Spec validation, normalized snapshot, Git baseline 기록
- Task scope 기반 Git 변경 수집과 argv 기반 check 실행
- check stdout/stderr, exit code, timeout을 포함한 mechanical Evidence 저장
- Canonical Verdict Schema와 runtime validation
- Canonical Run Integrity Validator와 Run Evidence Manifest
- raw-byte digest 및 `evidence_sha256` 기반 mechanical Evidence local consistency 확인
- portable verifier bundle 생성
- manual Verdict record/show와 fail-closed completion
- stable CLI exit code와 GitHub Actions CI
- wheel 설치 후 CLI와 packaged resource를 확인하는 clean-install 검증 경로

## Explicitly Not Included

- Pre/Post-check Source Snapshot 또는 verify 이후 current-source binding
- `--base-ref` 제거
- cryptographic signature, remote attestation, immutable ledger 또는 immutable storage
- complete secret redaction
- Multimodal Evidence
- 외부 verifier adapter, 모델 API, 외부 verifier CLI 호출
- runtime hook, approval token, Agent state machine, automatic verify/complete/repair
- worktree orchestration 또는 subagent topology 제어

## Trust Boundary

v0.1.0은 저장된 mechanical Evidence의 파일 존재, identity, raw-byte digest와
상호 일관성을 local filesystem 안에서 확인한다. `run-manifest.json`과
`evidence_sha256`은 이 local consistency를 식별하지만 cryptographic provenance,
completion authority, remote trust anchor, tamper-proof storage를 제공하지 않는다.

`harness complete`는 저장된 Run Evidence만 읽는다. check를 다시 실행하거나 Git diff를
다시 수집하지 않으며, verify 이후 현재 source가 바뀌었는지 비교하지 않는다.

## Known Limitations

- verify 이후 source 변경을 `complete`가 탐지하지 못한다.
- `verify --base-ref`는 Task snapshot의 baseline을 해당 Run에 한해 override할 수 있다.
- 동일한 로컬 사용자가 Evidence와 manifest를 함께 다시 계산해 변경하는 공격은 막지 못한다.
- signature, remote attestation, immutable storage가 없다.
- secret redaction은 완전하지 않으며, check log와 bundle을 공유하기 전에 사람이 검토해야 한다.

이 한계들은 v0.1.0 Experimental release의 공개된 제약이며 release blocker가 아니다.

## Compatibility

- Python 3.11 이상을 지원한다.
- public CLI와 stable exit code는 [Adapter CLI Contract](adapter-contract.ko.md)에 따른다.
- Adapter가 의존할 수 있는 JSON field와 read-only `.harness` artifact surface도 같은
  계약에 한정한다.
- `src/harness`의 Python module, dataclass, private function, Git 구현 세부사항은
  compatibility surface가 아니다.

## Upgrade Direction

후속 버전은 source binding을 별도 Run integrity 기능으로 추가하고, 그 다음
`--base-ref` 정책을 재검토한다. Multimodal Evidence와 optional external adapter는
그 이후의 별도 범위다. v0.1.0의 trust boundary를 후속 기능이 이미 제공하는 것처럼
해석해서는 안 된다.
