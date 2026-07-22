# Harness

Language: English | [한국어](README.ko.md)

> **Verify whether a completion claim is supported by evidence, without controlling how an Agent works.**

Harness is an experimental local CLI that packages changes made by a coding Agent, test results, a diff, and a review Verdict into a single Evidence Run.

There is a difference between an Agent saying “done” and leaving behind **evidence that can actually be reviewed**. Harness focuses on narrowing that gap.

> 🚧 **Status: Experimental**
>
> It is currently suited to personal projects, local experiments, and research into outcome-based completion gates.
>
> **v0.1.1 is the latest Experimental patch release.** Distribution artifacts are available from the
> [GitHub Release](https://github.com/jgoneit/harness/releases/tag/v0.1.1).

---

## 🎯 What problem does it solve?

Even when tests pass during a typical Agent task, the following problems can go unnoticed:

- Files outside the requested scope were changed
- Tests were weakened or bypassed
- The implementation exists but does not satisfy the actual objective
- The code at verification time differs from the code for which completion is claimed
- Test results contradict the stored Evidence

Harness does not restrict the Agent's reasoning or tool use.

Instead, after the work is done, it leaves behind material that can answer this question:

> **“Is there enough Evidence to claim that this result is complete?”**

---

## 🔄 How it works

```text
Task Spec
   ↓
Code changes
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

| Stage | Role |
| --- | --- |
| **Task Spec** | Define the objective, allowed scope, and checks |
| **Verify** | Store the diff and check results as Evidence |
| **Verifier Bundle** | Package a specific Run for independent review |
| **Manual Verdict** | Record the result of a human review of the Evidence |
| **Complete** | Determine whether the stored Evidence satisfies the completion conditions |

---

## ✨ Current features

- Task snapshots based on Git `HEAD`
- Scope-based changed-file collection
- Shell-free, argv-based check execution
- Recording of stdout, stderr, exit code, and timeout
- Storage of diff and mechanical verification Evidence
- A canonical integrity validator that uses a raw-byte manifest and digests to detect changes to stored mechanical Evidence
- Portable verifier bundles containing only a specific Task/Run
- Schema-based Manual Verdict validation
- Comparison of the raw Verdict with its validated snapshot
- Fail-closed completion that rejects unmet conditions
- Stable CLI exit codes
- unittest and GitHub Actions CI

### Features not yet provided

| Category | Details |
| --- | --- |
| **Intentional non-goals** | Controlling Agent reasoning, runtime hooks, process state machines, and worktree orchestration |
| **Known limitations** | No Pre/Post-check Source Snapshots or current-source binding; Run-level baseline override through `verify --base-ref`; no signatures, remote attestation, or immutable ledger |
| **External integrations** | Automatic invocation of Grok, xAI, the OpenAI API, or an external verifier CLI |
| **Evidence extensions** | Multimodal files, complete secret redaction, and automatic trust scoring |

---

## 📦 Installation

### Install from a release tag

```bash
python3 -m pip install \
  "git+https://github.com/jgoneit/harness.git@v0.1.1"
```

Once a wheel has been published to a GitHub Release, you can install the attached
`outcome_harness-0.1.1-py3-none-any.whl` file. The current distribution artifact is available from the
[v0.1.1 GitHub Release](https://github.com/jgoneit/harness/releases/tag/v0.1.1).

### Naming

The user-facing product, CLI, and Codex Plugin are all named **Harness**.

- CLI: `harness`
- Codex Plugin selection: `@harness`
- Explicit Codex Skill invocation: `$harness`

For compatibility with existing installations, the Python distribution and wheel filename retain
`outcome-harness` / `outcome_harness`.

### Install for development

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

### Requirements

- Python 3.11 or later
- A Git repository with at least one commit
- A local runtime capable of running the project's checks

### Supported platforms

- **macOS**: Supported. Checks run and are cleaned up in a separate POSIX process group.
- **Linux**: Uses the same POSIX process-group path as macOS.
- **Windows**: Cleans up the check process tree with a Job object. Children that intentionally
  request breakaway remain outside this cleanup boundary.

The only tests skipped on macOS are two boundary E2E tests for non-UTF-8 byte filenames that APFS
cannot create; they are not general functionality tests. Platform-independent unit tests continue to
verify the corresponding JSON escaping logic, so these skips do not mean that macOS support has been
withdrawn or the functionality abandoned.

---

## 🚀 Quick Start

The following example assumes a Python project with a `tests/` directory.

### 1. Create a check catalog

Create `.harness/checks.json` at the project root.

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

### 2. Define a Task

Create `task.json`.

```json
{
  "schema_version": 1,
  "id": "TASK-001",
  "type": "feature",
  "objective": "Add an API for retrieving user profiles.",
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

Create the Task snapshot.

```bash
harness task create --file task.json
```

The current Git `HEAD` is recorded as the Task's baseline.

### 3. Verify after changing the code

```bash
harness verify TASK-001
```

Example output:

```json
{
  "evidence_path": "/project/.harness/evidence/TASK-001/...",
  "run_id": "8d7ea7f77bc7430f9b2f7b97b31ecfa2"
}
```

Use the returned `run_id` in the commands that follow.

> `verify` is a command that **records verification results**. Even when a required check fails, the CLI exit code can be `0` if the Evidence was stored successfully. `complete` determines whether completion is actually allowed.

### 4. Create a Verifier Bundle

```bash
harness verifier bundle TASK-001 \
  --run-id <RUN_ID> \
  --output ./verifier-bundle
```

The Bundle contains the following information for the selected Run:

- Task snapshot
- List of changed files
- `diff.patch`
- Check results
- stdout / stderr
- Mechanical verification
- Verifier instructions

Creating a Bundle does not run a verifier or record a Verdict.

### 5. Write a Manual Verdict

Create `verdict.json`.

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
  "summary": "I reviewed the Evidence and found no blockers that would prevent completion.",
  "findings": [],
  "reviewed_at": "2026-07-16T00:00:00Z"
}
```

Record the Verdict for the Run.

```bash
harness verifier record TASK-001 \
  --run-id <RUN_ID> \
  --file verdict.json
```

Inspect the recorded Verdict.

```bash
harness verifier show TASK-001 --run-id <RUN_ID>
```

The only currently supported verifier kind is `manual`. Harness does not automatically call a model or external service.

### 6. Evaluate completion

```bash
harness complete TASK-001 --run-id <RUN_ID>
```

Completion succeeds only when all of the following conditions are met:

- The Task and Run identities match
- The required Evidence files exist
- The stored results do not contradict one another
- There are no scope violations
- All required checks passed
- No timeout occurred
- The mechanical result is `pass`
- The required verifier's Verdict is `pass`
- There are no blocker findings

A Task whose verifier is optional can complete without a Verdict. However, an already recorded Verdict cannot be ignored if it is `fail`, `unable`, or contains a blocker.

---

## 📁 Generated files

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
            ├── verification.json
            ├── run-manifest.json
            ├── verdict.raw.json
            ├── verdict.json
            └── completion.json
```

| File | Created by |
| --- | --- |
| `task.json` through `verification.json`, plus check logs | `harness verify` |
| `run-manifest.json` | The final step of `harness verify`, after storing the mechanical Evidence |
| `verdict.raw.json` | `harness verifier record` |
| `verdict.json` | `harness verifier record` |
| `completion.json` | A successful `harness complete` |

---

## 🧩 Core concepts

### Task Spec

Defines the objective, allowed scope of changes, check commands, risk level, and whether a verifier is required.

### Evidence Run

A verification record created by one execution of `verify`. Every Verdict and every Completion is tied to an explicit Task/Run pair.

### Mechanical Evidence

The diff, changed files, check results, and scope decision collected directly by Harness. It is separate from a Manual Verdict, which is a human semantic judgment.

### Run Evidence Manifest

`run-manifest.json` records, in sorted order, the Task/run identity and the relative path, raw-byte size, and SHA-256 digest of each mechanical Evidence file and check log. `evidence_sha256` is a local consistency identifier for the canonical JSON file records, excluding the timestamp. Verdict and Completion files are created after verification and therefore are not covered by the manifest.

### Manual Verdict

Schema-valid JSON written by a human after reviewing the Bundle. The input is preserved as `verdict.raw.json`, and the snapshot that passes schema validation is stored as `verdict.json`.

### Completion

The final gate that determines whether the stored Evidence and Verdict satisfy the completion conditions. `complete` does not rerun checks or recollect the Git diff.

### Trust boundary of the manifest

The manifest detects modified, missing, or replaced files at consumption time after verification, but it is not a signature, remote attestation, or immutable storage. It cannot prevent the same local user from recomputing and modifying both the Evidence and the entire manifest. `evidence_sha256` and the Bundle's `bundle_sha256` identify the original mechanical Evidence and portable bundle payload, respectively; neither is completion authority or an external trust anchor.

---

## 🔐 Trust and security boundaries

Harness currently provides:

- Shell-free check execution
- Explicit Task/Run identity
- A verifier Bundle with limited scope
- Revalidation of the raw Verdict and comparison with its validated snapshot
- Basic consistency checks among stored Evidence
- Rejection of completion when conditions are unmet

However, it does not guarantee:

- That the code remains unchanged after verification
- Protection against intentional manipulation of all Evidence by the same local user
- Cryptographic signatures
- Remote attestation
- Immutable storage
- Complete secret detection and redaction
- Actual verifier independence or fresh context

> ⚠️ Check stdout and stderr can contain sensitive information. Always inspect a Bundle before sharing it externally.

See [Architecture](docs/architecture.md) for more details.

---

## 🧪 Development and testing

Check the contract mirrors:

```bash
python3 scripts/sync_contracts.py --check
```

Run the full test suite:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

CI checks the following:

- Editable installation with development dependencies
- Consistency between the canonical contract and package resources
- unittest
- Git diff checks
- CLI execution from a clean wheel installation
- Access to the packaged Schema and verifier prompt

---

## 📚 Documentation

- [Architecture](docs/architecture.md)
- [Exit codes](docs/exit-codes.md)
- [v0.1.0 Release Scope](docs/release-scope-v0.1.0.md)
- [Adapter CLI Contract](docs/adapter-contract.md)
- [v0.1.0 Release Notes](docs/releases/v0.1.0.md)
- [v0.1.1 Release Notes](docs/releases/v0.1.1.md)
- [Task Schema](schemas/task.schema.json)
- [Verdict Schema](schemas/verdict.schema.json)
- [Verifier prompt](prompts/verifier.md)
- [Canonical Verdict Contract ADR](docs/adr/0001-canonical-verdict-contract.md)
- [Run Integrity ADR](docs/adr/0002-run-integrity-vs-completion-policy.md)
- [Run Evidence Manifest ADR](docs/adr/0003-run-evidence-manifest.md)

---

## 🛣️ Roadmap

Current priorities:

1. Pre/Post-check Snapshot binding
2. Removal of the `--base-ref` bypass

The Roadmap may change with the implementation sequence.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
