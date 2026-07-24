# Harness

Language: [English](README.md) | 한국어

> **Agent의 작업 방식을 통제하지 않고, 완료 주장이 Evidence로 뒷받침되는지
> 검증합니다.**

Harness는 Task snapshot, product 변경, check 결과, source identity를 검토 가능한
Evidence Run으로 저장하는 실험적 로컬 CLI입니다.

현재 main은 release되지 않은 `0.2.0.dev0`입니다. Source-bound verification
Evidence v2만 지원하며, 과거 v0.1.x Evidence를 in-place upgrade하지 않습니다.
자세한 내용은 [v0.2 verification Evidence migration](docs/migration-v0.2.md)을
참고하세요.

## Harness의 역할

Harness는 다음 질문에 답할 근거를 남깁니다.

> 저장된 Run이 현재 product source의 Task 완료 주장을 뒷받침하는가?

일반적인 “테스트 통과” 주장에 빠질 수 있는 다음 Evidence를 기록합니다.

- 저장된 Task 목표, Scope, check, risk, baseline commit
- committed, staged, unstaged, untracked product 변경
- binary-safe diff와 check stdout/stderr
- check 전 S0 및 check 후 S1 Source Snapshot
- raw-byte Run Manifest
- 선택적인 사용자 제공 Manual Verdict
- 명시적인 completion policy 결과

Harness는 tool을 가로채거나 구현 방식을 제한하지 않습니다. 모델 또는 external
verifier를 호출하지 않고, 코드를 자동 수리하지 않으며, immutable storage를
제공하지 않습니다.

## Workflow

```text
Task Spec
   │ harness task create
   ▼
Task snapshot + full baseline commit
   │ 구현
   ▼
harness verify: S0 → checks → S1
   ▼
저장된 Evidence v2
   ├── verifier bundle       선택적인 명시적 export
   ├── verifier record/show  선택적인 사용자 제공 Verdict
   └── complete              명시적인 S2 및 policy 평가
```

최소 기본 흐름은 `verify`가 Run을 저장하면 끝납니다. Bundle export, Verdict
작업, completion 평가는 명시적으로 요청할 때만 수행합니다.

## 설치

이 development contract에는 최종 v0.2 release artifact가 없습니다. 현재
checkout을 개발용으로 설치합니다.

```bash
git clone https://github.com/jgoneit/harness.git
cd harness
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[test,release]"
harness --version
```

요구사항:

- Python 3.11 이상
- Git

Python distribution 이름은 `outcome-harness`, console command와 Codex Plugin
이름은 `harness`입니다.

## Quick start

### 1. Check 설정

`.harness/checks.json`을 작성합니다.

```json
{
  "schema_version": 1,
  "checks": [
    {
      "name": "unit-test",
      "argv": ["python3", "-m", "unittest", "discover", "-s", "tests"],
      "required": true,
      "timeout_seconds": 60
    }
  ]
}
```

Check는 shell command 문자열이 아니라 argv 배열입니다. `task create`가 named
check를 saved Task snapshot에 풀어 쓰며, `verify`는 이후 그 저장 정의를
실행합니다.

### 2. Task 생성

`task.json`을 작성합니다.

```json
{
  "schema_version": 1,
  "id": "TASK-001",
  "type": "feature",
  "objective": "요청된 동작을 추가한다.",
  "scope": ["src", "tests"],
  "checks": ["unit-test"],
  "risk": "medium",
  "verifier": {
    "required": false
  }
}
```

정규화된 Task snapshot과 현재 full Git baseline을 저장합니다.

```bash
harness task create --file task.json
harness task show TASK-001
```

### 3. Verify

변경을 구현한 뒤 실행합니다.

```bash
harness verify TASK-001
```

Evidence 저장에 성공하면 다음을 출력합니다.

```json
{
  "evidence_path": "/path/to/repository/.harness/evidence/TASK-001/<RUN_ID>",
  "run_id": "<RUN_ID>"
}
```

Required check 실패, timeout, Scope violation, product source 변경이 있어도
Evidence를 안전하게 기록했다면 `verify`는 성공할 수 있습니다. 이는 저장된 실패
결과이며, completion policy는 `complete`가 적용합니다.

`verify --base-ref`는 지원하지 않습니다. Verification은 saved Task snapshot의
full baseline만 사용합니다.

### 선택적인 명시적 작업

Portable review bundle을 export합니다.

```bash
harness verifier bundle TASK-001 \
  --run-id <RUN_ID> \
  --output ./bundle-TASK-001
```

Bundle에는 검증된 historical S0/S1 Evidence가 포함됩니다. Check 재실행,
reviewer 실행, current S2 수집, Verdict 생성, Task completion은 수행하지 않습니다.

별도로 준비한 Manual Verdict를 기록하고 조회합니다.

```bash
harness verifier record TASK-001 \
  --run-id <RUN_ID> \
  --file verdict.json

harness verifier show TASK-001 --run-id <RUN_ID>
```

Completion을 평가합니다.

```bash
harness complete TASK-001 --run-id <RUN_ID>
```

Completion은 stored Evidence와 recorded Verdict를 검증하고 current S2를 수집한
뒤 S0 = S1 = S2를 요구합니다. 이후 verifier, Scope, timeout, required-check
gate를 적용합니다.

## Evidence v2

```text
.harness/
├── checks.json
├── tasks/
│   └── TASK-001.json
└── evidence/
    └── TASK-001/
        └── <RUN_ID>/
            ├── task.json
            ├── changed-files.json
            ├── diff.patch
            ├── checks.json
            ├── checks/
            │   ├── <check>.stdout
            │   └── <check>.stderr
            ├── source-before-checks.json
            ├── source-after-checks.json
            ├── verification.json
            ├── run-manifest.json
            ├── verdict.raw.json   # optional
            ├── verdict.json       # optional
            └── completion.json    # successful complete only
```

`verification.json`만 schema version 2를 사용합니다. Task, changed-files,
checks, Run Manifest, Source Snapshot, Bundle, Verdict, Completion schema
version은 기존 값을 유지합니다.

지원하지 않는 verification version, missing file, tampering, stored data
모순은 Evidence error(exit 8)입니다. Exit 9는 structurally valid v2 Run에서
S0와 S1 또는 S1과 S2가 달라 source binding이 실패한 경우에만 사용합니다.

## Trust와 security 경계

- Run Manifest는 mechanical file의 raw-byte size와 SHA-256으로 누락·변경을
  탐지합니다. Signature, remote attestation, immutable storage는 아닙니다.
- Bundle export는 현재 repository root와 user home의 알려진 spelling을
  치환합니다. 그 밖의 POSIX, Windows, UNC, URL 형태 text와 임의의 check-output
  byte는 보존합니다. 일반적인 path 익명화나 secret redaction이 아닙니다.
- Check log에는 민감한 값이 포함될 수 있으므로 외부 공유 전에 확인해야 합니다.
- Repository-local Codex credential policy는 별도 경계이며 Harness Core 기능이
  아닙니다.
- Source binding은 bounded observation입니다. S2 수집 이후 filesystem을
  잠그지 않습니다.

## 개발 검증

```bash
python3 scripts/sync_contracts.py --check
python3 -m unittest discover -s tests -v
python3 -m build
python3 -m twine check dist/*
python3 scripts/smoke_installed_cli.py --help
git diff --check
```

CI는 clean environment에 wheel을 설치해 CLI, public import, packaged contract
resource도 확인합니다.

## 문서

- [Architecture](docs/architecture.md)
- [Adapter CLI contract](docs/adapter-contract.md)
- [Exit codes](docs/exit-codes.md)
- [Credential boundary](docs/credential-boundary.md)
- [v0.2 Evidence migration](docs/migration-v0.2.md)
- [ADR 0000: Outcome Over Process (historical)](docs/adr/0000-outcome-over-process.md)
- [ADR 0001: Canonical Verdict Contract](docs/adr/0001-canonical-verdict-contract.md)
- [ADR 0002: Run Integrity and Completion Policy](docs/adr/0002-run-integrity-vs-completion-policy.md)
- [ADR 0003: Run Evidence Manifest](docs/adr/0003-run-evidence-manifest.md)
- [ADR 0004: Canonical Source Snapshot](docs/adr/0004-canonical-source-snapshot.md)
- [ADR 0005: Verify/Complete Source Binding](docs/adr/0005-verify-complete-source-binding.md)
- [v0.1.0 Release Notes](docs/releases/v0.1.0.md)
- [v0.1.1 Release Notes](docs/releases/v0.1.1.md)

## License

MIT License. 자세한 내용은 [LICENSE](LICENSE)를 참고하세요.
