# Seal

Language: [English](README.md) | 한국어

> **Evidence-backed completion for coding agents**

Seal은 public Outcome Harness Core CLI 위의 선택적 Codex Plugin입니다.
`Seal Plugin → public harness subprocess CLI → Outcome Harness Core` 계층을
사용합니다. Outcome Harness Core는 Task snapshot, product 변경, check 결과,
source identity를 검토 가능한 Evidence Run으로 저장하는 실험적 로컬 CLI입니다.

최신 Outcome Harness Core Experimental release는 `v0.2.1`입니다. Source-bound
verification Evidence v2만 지원하며, 과거 v0.1.x Evidence를 in-place upgrade하지 않습니다.
자세한 내용은 [v0.2 verification Evidence migration](docs/migration-v0.2.md)을
참고하세요.

현재 repository는 Core development version `0.3.0.dev0`과 source Plugin
development version `0.3.0-dev.0`을 사용합니다. Source Plugin은 Core
`>=0.3.0.dev0,<0.4.0`을 지원하고 읽기 전용 integrity-validated Run Summary
명령을 채택합니다. 최신 published Core와 Plugin release는 계속 `v0.2.1`이며,
해당 tag, artifact, release note, historical Plugin 동작은 변경하지 않습니다.

## Outcome Harness Core의 역할

Outcome Harness Core는 다음 질문에 답할 근거를 남깁니다.

> 저장된 Run이 현재 product source의 Task 완료 주장을 뒷받침하는가?

일반적인 “테스트 통과” 주장에 빠질 수 있는 다음 Evidence를 기록합니다.

- 저장된 Task 목표, Scope, check, risk, baseline commit
- committed, staged, unstaged, untracked product 변경
- binary-safe diff와 check stdout/stderr
- check 전 S0 및 check 후 S1 Source Snapshot
- raw-byte Run Manifest
- 선택적인 사용자 제공 Manual Verdict
- 명시적인 completion policy 결과

Outcome Harness Core는 tool을 가로채거나 구현 방식을 제한하지 않습니다. 모델
또는 external verifier를 호출하지 않고, 코드를 자동 수리하지 않으며, immutable
storage를 제공하지 않습니다.

## Core CLI workflow

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
   ├── run show              읽기 전용 validated state 조회
   ├── verifier bundle       선택적인 명시적 export
   ├── verifier record/show  선택적인 사용자 제공 Verdict
   └── complete              명시적인 S2 및 policy 평가
```

최소 기본 흐름은 `verify`가 Run을 저장하면 끝납니다. Bundle export, Verdict
작업, completion 평가는 명시적으로 요청할 때만 수행합니다.

### Profile

- **Basic mechanical-only profile:** `verifier.required`를 `false`로
  설정합니다. Source binding, Scope, timeout, required-check gate가 통과하면
  Manual Verdict 없이 `complete`가 성공할 수 있습니다.
- **Reviewed profile:** `verifier.required`를 `true`로 설정합니다.
  `complete`에는 별도로 준비된 blocker 없는 `pass` Manual Verdict도
  필요합니다.

Outcome Harness Core는 reviewer를 선택하거나 실행하지 않습니다. Bundle export는
검토를 위한 historical Evidence만 준비합니다.

## Seal Codex Plugin 관리형 workflow

위 Core CLI는 계속 명시적이고 서로 독립적인 작업 집합입니다. Seal Plugin은
literal 관리형 요청이나, 선택한 `@Seal` Plugin에 실행 가능한 coding outcome을
보낸 경우 같은 대화 안에서 UX를 연결합니다.

```text
$seal Swagger/OpenAPI를 도입하고 한글 API 설명까지 검증해줘

@Seal 선택: Swagger/OpenAPI를 도입하고 한글 API 설명까지 검증해줘
```

두 진입 방식 모두 실행 가능한 coding outcome이 있어야 합니다. 진입 방식과
무관하게 Plugin 선택만 한 경우와 토론, 설명, 계획, 감사, 리뷰, 상태 확인 요청은
Core를 시작하지 않고 답변합니다. 선택하지 않은 일반 coding 작업도 Seal을
활성화하지 않습니다.

관리형 응답은 간결한 mode와 status 요약을 먼저 보여줍니다. 전체 Task JSON과
check preview 앞에서 `Included in this confirmation`, `Not included in this
confirmation`, `Local records`를 구분해 승인 경계를 먼저 확인할 수 있게 합니다.

| 사용자 표시 status | 의미 |
| --- | --- |
| `Mode: Analysis only` | Core를 시작하지 않음 |
| `Status: Core unavailable` | 관리형 요청은 인식됐지만 호환 Core CLI를 사용할 수 없음 |
| `Status: Evidence recorded` | `verify`가 Run을 기록함. check 통과나 completion 결과는 아님 |
| `Status: Seal stopped` | 단계가 실패하거나 차단됐으며 자동 수리나 재시도를 하지 않음 |
| `Status: Review handoff ready` | Reviewed-profile bundle을 export했으며 reviewer나 Verdict 작업은 실행하지 않음 |

이 표시는 대화 표현일 뿐이며, persisted workflow state를 추가하거나 Core 권한을
바꾸지 않습니다.

`Status: Evidence recorded` 뒤에는 Core가 반환한 exact stored Run state를
compact하게 보여줍니다. `verify` exit 0은 Evidence 기록, `run show` exit 0은
stored Run integrity 검증 및 summary 직렬화를 뜻하며,
`mechanical_result=pass`는 저장된 mechanical state일 뿐입니다. 어느 것도
completion acceptance 또는 completion eligibility를 뜻하지 않습니다.

Plugin은 다음 순서로 동작합니다.

1. 요청한 결과로 Task 초안을 작성하고 Scope, catalog-derived check preview,
   HEAD baseline 의미, 기존 working-tree 변경을 보여줍니다.
2. Task 생성, 평소 방식의 구현, 최초 `verify` 정확히 1회, 그 성공한 verification이
   반환한 Run에 대한 `run show` 정확히 1회를 포함하는 한 번의 확인을 요청합니다.
   Reviewed profile이면 repository 밖의 fresh absolute directory에 local bundle을
   정확히 한 번 export하는 범위도 함께 표시합니다.
3. Task를 생성하고 성공 stdout에서 Core가 정규화한 authoritative check와
   정확한 Task ID를 최초 canonical repository root에 bind한 뒤 같은 대화에서
   연결하고 Coding Agent가 평소 방식으로 구현하게 합니다. saved Task field,
   baseline, check 중 하나라도 승인한 draft와 preview와 다르면 구현 전에
   중단하고 정확한 saved Task를 다시 명시적으로 채택받습니다.
4. 승인된 verification을 한 번 실행하고 exact Run ID와 opaque Evidence path를
   같은 repository root에 bind합니다. Root를 다시 resolve한 뒤 추가 질문 없이
   `harness run show <TASK_ID> --run-id <RUN_ID>`를 정확히 한 번 실행합니다. Exact
   `validated-run-summary/v1` object만 받아 Evidence digest, mechanical, Scope,
   required-check, source-stability, violation, per-check state를 보여주며 raw
   `verification.json`을 읽지 않습니다.
5. failed check, timeout, Scope violation, source instability를 포함한 모든 valid
   summary 뒤에도 adopted saved Task profile만 사용해 분기합니다. Basic profile은
   정확한 `complete` command를 보여주고 최종 확인을 요청하며, reviewed profile은
   승인된 local bundle을 한 번 export하고 별도로 준비된 Verdict를 기다립니다.
6. 별도로 제공된 Verdict는 명시적 요청에서만 기록하고, `complete` 직전에는 별도의
   최종 확인을 요청합니다. 같은 대화에서는 보존한 ID를 다시 복사할 필요가 없습니다.

최초 관리형 요청과 화면에 표시한 범위에 대한 사용자의 명확한 승인 답변이 함께
Task 생성, 구현, 최초 verification, exact Run Summary query, 해당하는 reviewed
profile의 local bundle 1회에 대한 명시적 요청을 이룹니다. 이는 Verdict
record/show, reviewer 실행, 외부 공유, `complete`, retry, repair, replacement Run을
승인하거나 일반 Codex permission prompt를 대신하지 않습니다.
Plugin이 직접 요청한 pending 확인에 대한
명확한 답변은 같은 workflow를 재개할 수 있지만, 무관한 승인과 일반 coding
요청에서는 Seal이 활성화되지 않습니다.

Task 생성, verification, `run show`, bundle, Verdict 기록, completion 중 하나가
실패하면 관리형 흐름은 중단합니다. Source를 자동 수리하거나 Evidence를 교체하고
alternate path를 선택하거나 새 Run을 만들거나 재시도하지 않습니다. 성공한
`verify` stdout은 계속 exact `{run_id, evidence_path}`이며, Plugin은 raw
`verification.json`을 읽지 않고 반환된 identity를 Core에 조회합니다. Summary의
missing/unknown key, identity/type mismatch, invalid envelope는 fail-closed로
중단합니다. Nonzero `run show`는 exact command, stdout, stderr, exit code를
보고하고 이전 성공 command가 반환한 identity만 보존하며 bundle, Verdict,
completion으로 진행하지 않습니다. Profile 분기에는 adopted saved
`verifier.required` field만 사용하고 completion은 Core만 판정합니다. Task ID와 Run
ID는 성공한 Core stdout과 최초 canonical repository root를 함께 보존한 경우에만
재사용하며 “latest” Task나 Run을 추론하지 않습니다.

모든 중단과 handoff는 단계, 정확한 Core 결과, 이전 성공 stdout에서 보존한
identity, 실행하지 않은 후속 작업, 다음으로 가능한 안전한 명시적 요청을 compact
capsule로 보여줍니다. Reviewed handoff는 bundle을 reviewer input으로, 별도로 준비한
Verdict를 expected output으로 표시하고, 보존한 identity를 재개할 정확한 record
요청도 안내합니다.

복구 및 고급 작업에는 저수준 Skill을 escape hatch로 사용합니다.

```text
$seal:task      Task 하나를 생성하거나 조회
$seal:verify    verification Run 하나를 기록하고 exact validated state까지 보여준 뒤 중단
$seal:bundle    정확한 Task와 Run 하나를 export
$seal:complete  최종 확인 후 정확한 Task와 Run 하나를 평가
```

각 저수준 Skill은 explicit-only입니다. Task 채택, ID, path, confirmation이
부족해 후속 요청이 필요하면 같은 namespaced invocation을 다시 포함해야 하며,
tag 없는 답변은 escape hatch를 활성화하지 않습니다.

`$seal:verify`는 bounded sequence입니다. 기존 preflight와 exact Task lookup 뒤
`verify` 한 번, 반환된 exact Run의 `run show` 한 번만 수행하고 Evidence identity와
validated stored state를 보고합니다. Bundle, Verdict, completion, repair, retry,
replacement Run으로 이어지지 않습니다.

`$seal:bundle`에서 output path를 생략하면 Plugin이 confirmed target repository
밖의 final directory가 존재하지 않는 unique absolute path를 선택하고, Core의 필수
`--output` argument로 전달합니다.

Bundle 성공은 Core가 export를 위해 저장 Run의 integrity를 검증했다는 뜻입니다.
Mechanical outcome pass나 completion eligibility를 의미하지는 않습니다.

구현 대화는 승인된 reviewed-profile bundle 1회까지 준비할 수 있지만 독립 Verdict를
만들지는 않습니다. Stored Run integrity, Verdict validation, source binding,
completion의 권한은 계속 Core에 있습니다.

별도로 제공하는 Verdict input은 target repository 밖에 둡니다. Plugin이 inline
Verdict JSON을 파일로 만들 때도 repository 밖의 temporary file을 사용해 input
자체가 검증된 product source를 바꾸지 않게 합니다.

## 설치

### Core CLI

`v0.2.1` tag를 설치합니다.

```bash
python3 -m pip install \
  "git+https://github.com/jgoneit/seal.git@v0.2.1"
harness --version
```

이 pip command는 Core만 설치하며 Codex Plugin을 설치하지 않습니다.

Release artifact 이름은 `outcome_harness-0.2.1-py3-none-any.whl`과
`outcome_harness-0.2.1.tar.gz`입니다.

요구사항:

- Python 3.11 이상
- Git

Python distribution 이름은 `outcome-harness`, console command는 `harness`,
current Codex Plugin 이름은 `seal`입니다.

### Codex Plugin

Source Plugin manifest는 `0.3.0-dev.0`이며 published release가 아닌 development
line을 엽니다. Core `>=0.3.0.dev0,<0.4.0`이 필요하고 Core 0.2.x와 호환되지
않습니다. 최신 published Plugin은 계속 `v0.2.1`입니다. 이 checkout을 가리키는
personal marketplace entry에서는 Core package와 별도로 Plugin을 설치하거나
갱신합니다.

```bash
codex plugin add seal@personal
```

Codex는 Plugin content를 cache합니다. 설치 또는 갱신 후 refreshed Skill과
metadata를 읽도록 새 Codex task를 시작합니다.

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

#### Core 0.3 development: 검증된 Run 상태 조회

`0.3.0.dev0` development line에서는 raw `verification.json`을 직접 읽지 않고
정확한 stored Run 하나를 조회할 수 있습니다.

```bash
harness run show TASK-001 --run-id <RUN_ID>
```

명령은 [Adapter CLI Contract](docs/adapter-contract.md)에 정의한 exact
`validated-run-summary/v1` envelope를 반환합니다. Canonical stored-Run
validator를 호출할 뿐 파일을 쓰거나 lifecycle transition을 수행하지 않고,
latest Run도 추론하지 않습니다. 구조적으로 유효한 failed Run은 실패 상태를
JSON에 담아 exit 0으로 반환하고, missing/corrupt Evidence는 exit 8입니다. Check
재실행, S2 수집, Verdict/completion 상태 조회, reviewer 호출, retry, repair, next
action 추천은 수행하지 않습니다.

Source Seal Plugin `0.3.0-dev.0`은 managed flow 또는 `$seal:verify`의 성공한 한 번의
verification이 반환한 Run에 대해 이 exact command를 자동으로 한 번 실행합니다.
Stored state를 보여주기 전에 envelope를 검증하며 raw `verification.json`을
소비하지 않습니다.

### 고급 및 복구 작업

Portable review bundle을 export합니다.

```bash
harness verifier bundle TASK-001 \
  --run-id <RUN_ID> \
  --output <OUTPUT_DIR_OUTSIDE_REPOSITORY>
```

Bundle에는 검증된 historical S0/S1 Evidence가 포함됩니다. Check 재실행,
reviewer 실행, current S2 수집, Verdict 생성, Task completion은 수행하지 않습니다.
Output을 target repository 밖에 두면 verification 이후 product source가 바뀌는
것을 피할 수 있습니다.

별도로 준비한 Manual Verdict를 기록하고 조회합니다.

```bash
harness verifier record TASK-001 \
  --run-id <RUN_ID> \
  --file <VERDICT_JSON_OUTSIDE_REPOSITORY>

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

## v0.1.x compatibility

Harness v0.2.x는 v0.1.x verification Run을 읽지 않습니다. 해당 Evidence는
대응하는 v0.1.x tag의 CLI로 읽어야 합니다. In-place migration은 없으며,
source-bound completion claim에는 v0.2.x CLI로 새 Evidence v2 Run을 생성해야
합니다.

## Trust와 security 경계

- Seal은 Plugin branding이며 signature, remote attestation, immutable 또는
  tamper-proof store, non-repudiation 보장, external trust anchor가 아닙니다.
- Run Manifest는 mechanical file의 raw-byte size와 SHA-256으로 누락·변경을
  탐지합니다. Signature가 아니며, local user가 Evidence와 manifest를 함께
  다시 쓰는 상황을 방어하지 않습니다.
- Bundle export는 현재 repository root와 user home의 알려진 spelling을
  치환합니다. 그 밖의 POSIX, Windows, UNC, URL 형태 text와 임의의 check-output
  byte는 보존합니다. 일반적인 path 익명화나 secret redaction이 아닙니다.
- Check log에는 민감한 값이 포함될 수 있으므로 외부 공유 전에 확인해야 합니다.
- `complete`는 저장된 check 결과를 검증하며 check를 재실행하거나 secret을
  redact하지 않습니다.
- Source binding은 local bounded observation입니다. S2 수집 이후 또는
  `complete` 반환 이후 filesystem을 잠그지 않습니다.
- Manual Verdict 기록은 Verdict를 Task와 Run에 bind하지만 reviewer가 실제로
  독립적이었음을 보장하지 않습니다.
- Local Evidence는 immutable central audit store가 아니며, v0.2.x는 모든
  특수 Git state 지원을 주장하지 않습니다.
- Repository-local Codex credential policy는 별도 경계이며 Harness Core 기능이
  아닙니다.

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
- [Seal Codex UI smoke](docs/seal-ui-smoke.md)
- [Exit codes](docs/exit-codes.md)
- [Credential boundary](docs/credential-boundary.md)
- [v0.2 Evidence migration](docs/migration-v0.2.md)
- [ADR 0000: Outcome Over Process (historical)](docs/adr/0000-outcome-over-process.md)
- [ADR 0001: Canonical Verdict Contract](docs/adr/0001-canonical-verdict-contract.md)
- [ADR 0002: Run Integrity and Completion Policy](docs/adr/0002-run-integrity-vs-completion-policy.md)
- [ADR 0003: Run Evidence Manifest](docs/adr/0003-run-evidence-manifest.md)
- [ADR 0004: Canonical Source Snapshot](docs/adr/0004-canonical-source-snapshot.md)
- [ADR 0005: Verify/Complete Source Binding](docs/adr/0005-verify-complete-source-binding.md)
- [v0.2.1 Release Notes](docs/releases/v0.2.1.md)
- [v0.2.0 Release Notes](docs/releases/v0.2.0.md)
- [v0.1.0 Release Notes](docs/releases/v0.1.0.md)
- [v0.1.1 Release Notes](docs/releases/v0.1.1.md)

## License

MIT License. 자세한 내용은 [LICENSE](LICENSE)를 참고하세요.
