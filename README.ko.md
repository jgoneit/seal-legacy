# Harness

Language: [English](README.md) | 한국어

> **Agent의 작업 방식을 통제하지 않고, 완료 주장에 근거가 있는지를 검증합니다.**

Harness는 코딩 Agent가 만든 변경 사항, 테스트 결과, diff, 검토 Verdict를 하나의 Evidence Run으로 묶는 실험적 로컬 CLI입니다.

Agent가 “완료했습니다”라고 말하는 것과, 실제로 **검토 가능한 근거를 남긴 것**은 다릅니다. Harness는 그 간극을 줄이는 데 집중합니다.

> 🚧 **Status: Experimental**
>
> 현재는 개인 프로젝트, 로컬 실험, outcome-based completion gate 연구에 적합합니다.
>
> **v0.1.1은 최신 Experimental patch release입니다.** 배포 파일은
> [GitHub Release](https://github.com/jgoneit/harness/releases/tag/v0.1.1)에서 받을 수 있습니다.
>
> **Current main은 unreleased `0.2.0.dev0` development line입니다.** 아래에서
> 설명하는 source-bound verification과 completion을 추가합니다.
> `0.2.0.dev0` tag나 release artifact는 배포하지 않았습니다.

---

## 🎯 무엇을 해결하나요?

일반적인 Agent 작업에서는 테스트가 통과하더라도 다음 문제를 놓칠 수 있습니다.

- 요청 범위를 벗어난 파일이 수정됨
- 테스트가 약화되거나 우회됨
- 구현은 됐지만 실제 목표를 충족하지 못함
- 검증 당시 코드와 완료를 선언하는 코드가 달라짐
- 테스트 결과와 저장된 Evidence가 서로 모순됨

Harness는 Agent의 reasoning이나 tool 사용을 막지 않습니다.

대신 작업이 끝난 뒤 다음 질문에 답할 수 있는 자료를 남깁니다.

> **“이 결과를 완료라고 주장할 충분한 Evidence가 있는가?”**

---

## 🔄 동작 방식

```text
Task Spec
   ↓
코드 변경
   ↓
harness verify
   ↓
Evidence Run
   ↓
Verifier Bundle
   ↓
Manual Verdict
   ↓
harness complete
```

| 단계 | 역할 |
| --- | --- |
| **Task Spec** | 작업 목적, 수정 범위, 검사 항목 정의 |
| **Verify** | diff와 check 결과를 Evidence로 저장 |
| **Verifier Bundle** | 특정 Run만 독립적으로 검토할 수 있게 패키징 |
| **Manual Verdict** | 사람이 Evidence를 검토한 결과 기록 |
| **Complete** | 저장된 Evidence가 완료 조건을 충족하는지 판정 |

---

## ✨ 현재 제공하는 기능

- Git `HEAD`를 기준으로 한 Task snapshot
- scope 기반 변경 파일 수집
- shell을 사용하지 않는 argv 기반 check 실행
- stdout, stderr, exit code, timeout 기록
- diff와 mechanical verification Evidence 저장
- 각 새 Run의 canonical pre-check/post-check product-source Snapshot
- Successful completion 전 current-source 비교
- raw-byte manifest와 digest로 저장 mechanical Evidence 변경을 탐지하는 canonical integrity validator
- 특정 Task/Run만 포함하는 portable verifier bundle
- Schema 기반 Manual Verdict 검증
- raw Verdict와 검증된 snapshot 비교
- 조건 미충족 시 거부하는 fail-closed completion
- 안정적인 CLI exit code
- unittest와 GitHub Actions CI

### 아직 제공하지 않는 기능

| 구분 | 내용 |
| --- | --- |
| **의도적 비목표** | Agent reasoning 통제, runtime hook, process state machine, worktree orchestration |
| **알려진 한계** | Source Binding은 filesystem lock이 아닌 bounded local observation이며, signature, remote attestation, immutable ledger, Task revision, CI pull-request base/head model은 없음 |
| **외부 연동** | Grok, xAI, OpenAI API 및 외부 verifier CLI 자동 호출 |
| **Evidence 확장** | 멀티모달 파일, 완전한 secret redaction, automatic trust scoring |

---

## 📦 설치

### Release tag에서 설치

```bash
python3 -m pip install \
  "git+https://github.com/jgoneit/harness.git@v0.1.1"
```

GitHub Release에서 wheel이 실제로 발행된 뒤에는 해당 Release에 첨부된
`outcome_harness-0.1.1-py3-none-any.whl` 파일을 설치할 수 있습니다. 현재 배포 파일은
[v0.1.1 GitHub Release](https://github.com/jgoneit/harness/releases/tag/v0.1.1)에 있습니다.

Release-tag install은 S0/S1/S2 Source Binding이 없는 legacy v0.1.1 contract를
사용합니다. 이후 release가 배포되기 전까지 이 README의 source-bound 동작에는
current-main development install이 필요합니다.

### 이름

사용자에게 보이는 제품, CLI, Codex Plugin 이름은 모두 **Harness**입니다.

- CLI: `harness`
- Codex Plugin 선택: `@harness`
- Codex Skill 명시 호출: `$harness`

기존 설치 호환성을 위해 Python distribution과 wheel 파일명에는
`outcome-harness` / `outcome_harness`가 남아 있습니다.

### 개발 환경에서 설치

```bash
git clone https://github.com/jgoneit/harness.git
cd harness

python3 -m venv .venv
source .venv/bin/activate

python3 -m pip install -e '.[test]'
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 요구사항

- Python 3.11 이상
- 최소 1개 이상의 commit이 존재하는 Git repository
- 프로젝트 check를 실행할 수 있는 로컬 runtime

### 지원 플랫폼

- **macOS**: 지원합니다. check는 별도 POSIX process group에서 실행·정리됩니다.
- **Linux**: macOS와 같은 POSIX process-group 경로를 사용합니다.
- **Windows**: Job object 기반으로 check process tree를 정리합니다. 의도적으로
  breakaway를 요청한 child는 이 cleanup 경계 밖에 남습니다.

macOS에서 건너뛰는 것은 일반 기능이 아니라, APFS가 만들 수 없는 비-UTF-8 바이트
파일명을 다루는 경계 E2E 두 건뿐입니다. 해당 JSON escaping 로직은 플랫폼과 무관한
unit test로 계속 검증하므로, 이 skip은 macOS 지원 중단이나 기능 포기를 뜻하지 않습니다.

---

## 🚀 Quick Start

아래 예시는 `tests/` 디렉터리가 있는 Python 프로젝트를 기준으로 합니다.

### 1. Check catalog 작성

프로젝트 root에 `.harness/checks.json`을 만듭니다.

```json
{
  "schema_version": 1,
  "checks": [
    {
      "name": "unit-test",
      "argv": [
        "python3",
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests"
      ],
      "required": true,
      "timeout_seconds": 60
    }
  ]
}
```

### 2. Task 정의

`task.json`을 작성합니다.

```json
{
  "schema_version": 1,
  "id": "TASK-001",
  "type": "feature",
  "objective": "사용자 프로필 조회 API를 추가한다.",
  "scope": [
    "src",
    "tests"
  ],
  "checks": [
    "unit-test"
  ],
  "risk": "medium",
  "verifier": {
    "required": true
  }
}
```

Task snapshot을 생성합니다.

```bash
harness task create --file task.json
```

이때 현재 Git `HEAD`가 Task의 baseline으로 기록됩니다.

### 3. 코드 변경 후 검증

```bash
harness verify TASK-001
```

Verification은 항상 Task에 저장된 baseline을 사용하며 Run 단위 `--base-ref`
override는 없습니다. Current-main verification은 check 직전 canonical
product-source Snapshot(S0)과 모든 check 종료 직후 Snapshot(S1)을 수집합니다.
Required 또는 optional check가 product source를 바꾸면 check 자체가 통과해도
Run의 mechanical result는 fail입니다.

출력 예시:

```json
{
  "evidence_path": "/project/.harness/evidence/TASK-001/...",
  "run_id": "8d7ea7f77bc7430f9b2f7b97b31ecfa2"
}
```

이후 명령에서는 출력된 `run_id`를 사용합니다.

> `verify`는 검증 결과를 **기록하는 명령**입니다. Required check가 실패하거나
> timeout이 나거나 product source를 바꿔도 versioned Evidence 저장에 성공했다면
> CLI exit code는 `0`일 수 있습니다. 실제 완료 가능 여부는 `complete`가
> 판단합니다. S0 또는 S1을 수집하지 못하면 valid manifest나 성공 결과를 만들지
> 않습니다.

### 4. Verifier Bundle 생성

```bash
harness verifier bundle TASK-001 \
  --run-id <RUN_ID> \
  --output ./verifier-bundle
```

Bundle에는 선택한 Run의 다음 정보가 포함됩니다.

- Task snapshot
- 변경 파일 목록
- `diff.patch`
- check 결과
- stdout / stderr
- mechanical verification
- v2 Run의 pre-check S0과 post-check S1 Source Snapshot
- verifier instruction

Bundle 생성만으로 verifier가 실행되거나 Verdict가 기록되지는 않습니다. 또한
current completion-time S2 Snapshot을 수집하거나 current source를 비교하거나
check를 재실행하거나 completion을 판정하지 않습니다.

### 5. Manual Verdict 작성

`verdict.json`을 작성합니다.

```json
{
  "schema_version": 1,
  "task_id": "TASK-001",
  "run_id": "8d7ea7f77bc7430f9b2f7b97b31ecfa2",
  "verifier": {
    "kind": "manual",
    "runner": "human",
    "model": null,
    "fresh_context": true
  },
  "verdict": "pass",
  "summary": "Evidence를 검토했고 completion을 막을 blocker를 찾지 못했다.",
  "findings": [],
  "reviewed_at": "2026-07-16T00:00:00Z"
}
```

Verdict를 Run에 기록합니다.

```bash
harness verifier record TASK-001 \
  --run-id <RUN_ID> \
  --file verdict.json
```

기록된 Verdict를 확인합니다.

```bash
harness verifier show TASK-001 --run-id <RUN_ID>
```

현재 지원하는 verifier kind는 `manual`뿐입니다. Harness가 모델이나 외부 서비스를 자동 호출하지는 않습니다.

### 6. 완료 판정

```bash
harness complete TASK-001 --run-id <RUN_ID>
```

Completion이 성공하려면 다음 조건을 모두 만족해야 합니다.

- Task와 Run identity가 일치함
- 필요한 Evidence 파일이 존재함
- 저장된 결과 사이에 모순이 없음
- Run이 source-bound verification Evidence v2를 사용함
- Pre-check S0과 post-check S1 Snapshot이 일치함
- Current completion-time S2 Snapshot이 S1과 일치함
- scope 위반이 없음
- 모든 required check가 성공함
- timeout이 없음
- mechanical result가 `pass`
- required verifier의 Verdict가 `pass`
- blocker finding이 없음

Verifier가 optional인 Task는 Verdict 없이 completion할 수 있습니다. 단, 이미 기록된 Verdict가 `fail`, `unable`이거나 blocker를 포함한다면 이를 무시하고 완료할 수 없습니다.

Legacy verification v1 Run은 계속 읽고 bundle로 만들고 Verdict record/show에
사용할 수 있지만 current-main completion은 exit 9로 거부합니다. 새 v2
verification Run이 필요하며 historical Evidence를 in-place upgrade하지 않습니다.

`verification.json`만 schema version 2로 올라갑니다. Task, changed-files,
checks, Run manifest, bundle, Verdict, Completion document schema는 version 1을
유지하며 두 Source Snapshot document도 별도 Snapshot contract의 version 1을
사용합니다.

---

## 📁 생성되는 파일

아래 tree는 current source-bound verification v2 Run을 나타냅니다. Legacy v1
Run에는 두 Source Snapshot file이 없습니다.

```text
.harness/
├── checks.json
├── tasks/
│   └── <TASK_ID>.json
└── evidence/
    └── <TASK_ID>/
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
            ├── verdict.raw.json
            ├── verdict.json
            └── completion.json
```

| 파일 | 생성 시점 |
| --- | --- |
| `task.json`부터 두 Source Snapshot document와 `verification.json`, check log | `harness verify` |
| `run-manifest.json` | `harness verify`가 mechanical Evidence 저장을 마친 마지막 단계 |
| `verdict.raw.json` | `harness verifier record` |
| `verdict.json` | `harness verifier record` |
| `completion.json` | `harness complete` 성공 시 |

---

## 🧩 핵심 개념

### Task Spec

작업의 목적, 허용된 수정 범위, 검사 명령, 위험도, verifier 필요 여부를 정의합니다.

### Evidence Run

한 번의 `verify` 실행으로 생성된 검증 기록입니다. 모든 Verdict와 Completion은 명시적인 Task/Run 쌍에 연결됩니다.

### Mechanical Evidence

Harness가 직접 수집한 diff, 변경 파일, check 결과, Source Snapshot, scope와
source stability 판정입니다. 사람의 의미적 판단인 Manual Verdict와는 별개입니다.

### Source Binding

Verification v2 Run에서 S0은 check 직전 product source, S1은 모든 check 종료 직후
product source를 식별합니다. Completion에서 Harness는 current source를 S2로
수집하고 verifier, scope, timeout, required-check gate를 적용하기 전에
S0 = S1 = S2를 요구합니다. S2는 live comparison이며 Evidence로 저장하지 않습니다.

Snapshot identity는 저장된 Task baseline 대비 final product byte, path, normalized
executable mode, symlink target을 나타냅니다. 동일한 final source를 unstaged,
staged, committed 상태 사이에서 이동해도 identity는 바뀌지 않습니다. Gitignored
untracked file과 canonical Harness metadata는 제외하며 Task Scope는 Snapshot
identity를 제한하지 않습니다.

### Run Evidence Manifest

`run-manifest.json`은 Task/run identity와 mechanical Evidence file·check log의
relative path, raw-byte size, SHA-256을 정렬해 기록하며 v2 Run의 S0과 S1도
포함합니다. `evidence_sha256`은 timestamp를 제외한 canonical JSON file record의
local consistency identifier입니다. Verdict와 Completion은 verify 이후에 생기므로
manifest 대상이 아닙니다.

### Manual Verdict

사람이 Bundle을 검토하고 작성한 Schema-valid JSON입니다. 입력 원본은 `verdict.raw.json`으로 보존하고, schema 검증을 통과한 snapshot은 `verdict.json`으로 저장합니다.

### Completion

Stored Evidence, 기록된 Verdict, current S2 source identity가 완료 조건을
만족하는지 판단하는 마지막 gate입니다. `complete`는 check를 다시 실행하거나
Git diff를 다시 수집하지 않습니다.

### Manifest의 신뢰 경계

manifest는 verify 이후 파일 수정·누락·교체를 소비 시점에 탐지하지만 signature, remote attestation, immutable storage가 아닙니다. 동일한 로컬 사용자가 Evidence와 manifest 전체를 다시 계산해 바꾸는 공격은 막지 못합니다. `evidence_sha256`과 bundle의 `bundle_sha256`은 각각 원본 mechanical Evidence와 portable bundle payload를 식별할 뿐, completion authority나 외부 trust anchor가 아닙니다.

---

## 🔐 신뢰와 보안 경계

Harness는 현재 다음을 제공합니다.

- shell 없는 check 실행
- 명시적인 Task/Run identity
- 제한된 범위의 verifier bundle
- raw Verdict와 검증된 snapshot 재검증
- 저장 Evidence 간 기본 consistency 검사
- Verification 전후 source stability와 completion-time current-source 비교
- 조건 미충족 시 completion 거부

하지만 다음을 보장하지는 않습니다.

- Bounded S2 observation 뒤 또는 `complete` 반환 뒤 source가 그대로 유지됨
- 동일한 로컬 사용자의 의도적인 전체 Evidence 조작 방어
- cryptographic signature
- remote attestation
- immutable storage
- 완전한 secret detection과 redaction
- verifier의 실제 독립성 또는 fresh context

> ⚠️ Check의 stdout과 stderr에는 민감한 정보가 포함될 수 있습니다. Bundle은 외부 공유 전에 반드시 내용을 확인하세요.

자세한 구조는 [Architecture](docs/architecture.ko.md)를 참고하세요.

---

## 🧪 개발과 테스트

Contract mirror 확인:

```bash
python3 scripts/sync_contracts.py --check
```

전체 테스트 실행:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

CI에서는 다음을 검사합니다.

- 개발 의존성을 포함한 editable 설치
- Canonical contract와 package resource 일치
- unittest
- Git diff 검사
- wheel 기반 clean install의 CLI 실행
- packaged Schema와 verifier prompt 접근

---

## 📚 문서

- [Architecture](docs/architecture.ko.md)
- [Codex credential 경계](docs/credential-boundary.ko.md)
- [Exit codes](docs/exit-codes.ko.md)
- [v0.1.0 Release Scope](docs/release-scope-v0.1.0.ko.md)
- [Adapter CLI Contract](docs/adapter-contract.ko.md)
- [v0.1.0 Release Notes](docs/releases/v0.1.0.ko.md)
- [v0.1.1 Release Notes](docs/releases/v0.1.1.ko.md)
- [Task Schema](schemas/task.schema.json)
- [Verification Schema](schemas/verification.schema.json)
- [Verdict Schema](schemas/verdict.schema.json)
- [Verifier prompt](prompts/verifier.md)
- [Canonical Verdict Contract ADR](docs/adr/0001-canonical-verdict-contract.ko.md)
- [Run Integrity ADR](docs/adr/0002-run-integrity-vs-completion-policy.ko.md)
- [Run Evidence Manifest ADR](docs/adr/0003-run-evidence-manifest.ko.md)
- [Canonical Source Snapshot ADR](docs/adr/0004-canonical-source-snapshot.ko.md)
- [Verify/Complete Source Binding ADR](docs/adr/0005-verify-complete-source-binding.ko.md)

---

## 🛣️ Roadmap

Current main은 pre/post-check Snapshot binding을 완료하고 Run 단위
`--base-ref` 우회를 제거했습니다. 이후 가능한 작업은 의도적으로 분리합니다.

1. 저장 baseline을 의도적으로 바꾸는 Task revision policy
2. CI 전용 pull-request base/head command와 contract
3. Optional cryptographic 또는 remote trust anchor

Roadmap은 구현 순서에 따라 변경될 수 있습니다.

---

## License

MIT License. 자세한 내용은 [LICENSE](LICENSE)를 참고하세요.
