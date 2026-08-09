# Harness

Language: English | [한국어](README.ko.md)

> **Verify whether a completion claim is supported by evidence, without
> controlling how an Agent works.**

Harness is an experimental local CLI that saves a Task snapshot, product
changes, check results, and source identity as a reviewable Evidence Run.

The latest Experimental release is `v0.2.1`. It supports source-bound
verification Evidence v2 only. Historical v0.1.x Evidence is not upgraded in
place; see
[Migrating verification Evidence to v0.2](docs/migration-v0.2.md).

## What Harness does

Harness helps answer:

> Does this saved Run support the claim that the current product source
> completed the requested Task?

It records evidence that ordinary “tests passed” claims can omit:

- the saved Task objective, Scope, checks, risk, and baseline commit;
- committed, staged, unstaged, and untracked product changes;
- binary-safe diff and check stdout/stderr;
- pre-check S0 and post-check S1 Source Snapshots;
- a raw-byte Run Manifest;
- an optional user-provided Manual Verdict; and
- explicit completion policy results.

Harness does not intercept tools, restrict implementation choices, call a
model, execute an external verifier, repair code, or provide immutable storage.

## Core CLI workflow

```text
Task Spec
   │ harness task create
   ▼
Task snapshot + full baseline commit
   │ implementation
   ▼
harness verify: S0 → checks → S1
   ▼
Saved Evidence v2
   ├── verifier bundle       optional explicit export
   ├── verifier record/show  optional user-provided Verdict
   └── complete              explicit S2 and policy evaluation
```

The minimum default flow ends when `verify` saves the Run. Bundle export,
Verdict operations, and completion evaluation occur only when explicitly
requested.

### Profiles

- **Basic mechanical-only profile:** set `verifier.required` to `false`.
  `complete` can succeed without a Manual Verdict when source binding, Scope,
  timeout, and required-check gates pass.
- **Reviewed profile:** set `verifier.required` to `true`. `complete` also
  requires a separately prepared `pass` Manual Verdict with no blockers.

Harness never selects or runs the reviewer. Bundle export only prepares
historical Evidence for review.

## Codex Plugin managed workflow

The Core CLI above remains a set of explicit, independent operations. The
Codex Plugin adds a conversation-scoped UX for either a literal managed request
or an executable coding outcome sent with the explicitly selected `@Harness`
Plugin:

```text
$harness Add Swagger/OpenAPI and verify the Korean API descriptions.

@Harness selected: Add Swagger/OpenAPI and verify the Korean API descriptions.
```

Both entry forms require an executable coding outcome. Regardless of entry
form, Plugin selection alone and discussion, explanation, planning, audit,
review, or status requests are answered without starting Core. Ordinary
unselected coding work does not activate it either.

The Plugin then:

1. drafts the Task from the requested outcome and shows its Scope, a
   catalog-derived check preview, HEAD baseline semantics, and existing
   working-tree changes;
2. asks for one confirmation covering Task creation, ordinary implementation,
   and the first `verify` exactly once. For a reviewed profile, the displayed
   coverage also includes exactly one local bundle export to a fresh absolute
   directory outside the repository;
3. creates the Task, reports Core's authoritative normalized checks from
   successful stdout, binds the exact Task ID to the original canonical
   repository root in the same conversation, and lets the coding Agent
   implement normally; if the saved Task fields, baseline, or checks differ
   from the approved draft and preview, it stops for explicit re-adoption first;
4. runs the approved verification once, binds the exact Run ID and opaque
   Evidence path to the same repository root, and reports that Evidence
   identity. It then branches only on the adopted saved Task profile: a basic
   profile shows the exact `complete` command and asks for final confirmation;
   a reviewed profile exports the one approved local bundle and pauses for an
   independently prepared Verdict; and
5. records a separately supplied Verdict only on an explicit request, then asks
   for final confirmation immediately before `complete`. The retained IDs do
   not need to be copied again in the same conversation.

Together, the initial managed request and the user's affirmative reply to the
displayed covered actions form the explicit request for Task creation,
implementation, the first verification, and the reviewed profile's one local
bundle when applicable. They do not authorize Verdict record/show, reviewer
invocation, external sharing, `complete`, or a replacement for normal Codex
permission prompts.
An unambiguous reply to the Plugin's own pending confirmation may resume the
same workflow; unrelated approvals and ordinary coding requests do not
activate Harness.

If Task creation, verification, bundle, Verdict recording, or completion fails,
the managed flow stops. It does not repair source, replace Evidence, choose an
alternate path, create another Run, or retry automatically. Successful `verify`
stdout in Core `0.2.x` records Evidence but does not expose an
integrity-validated mechanical summary. The Plugin does not read raw
`verification.json`; profile routing uses only the adopted saved
`verifier.required` field, and Core alone decides completion. Task and Run IDs
are reused only from successful Core stdout and only with their original
canonical repository root; the Plugin does not infer a “latest” Task or Run.

Use the low-level Skills as recovery and advanced escape hatches:

```text
$harness:task      create or inspect one Task
$harness:verify    record one verification Run
$harness:bundle    export one exact Task and Run
$harness:complete  evaluate one exact Task and Run after final confirmation
```

Each low-level Skill is explicit-only. If it needs a missing adoption, ID,
path, or confirmation, repeat the same namespaced invocation in the follow-up;
an untagged reply does not activate an escape hatch.

If `$harness:bundle` omits an output path, the Plugin chooses a unique absolute
path outside the confirmed target repository whose final directory does not
exist, then passes it to Core's required `--output` argument.

Bundle success means Core validated the stored Run's integrity for export. It
does not mean the mechanical outcome passed or that the Run is eligible for
completion.

The implementation conversation may prepare the one approved reviewed-profile
bundle, but it does not create an independent Verdict. Core remains the
authority for stored Run integrity, Verdict validation, source binding, and
completion.

Keep separately supplied Verdict input outside the target repository. If the
Plugin materializes inline Verdict JSON, it uses an external temporary file so
the input itself does not change verified product source.

## Installation

### Core CLI

Install the `v0.2.1` tag:

```bash
python3 -m pip install \
  "git+https://github.com/jgoneit/harness.git@v0.2.1"
harness --version
```

This pip command installs Core only; it does not install the Codex Plugin.

The release artifact names are
`outcome_harness-0.2.1-py3-none-any.whl` and
`outcome_harness-0.2.1.tar.gz`.

Requirements:

- Python 3.11 or later
- Git

The Python distribution name is `outcome-harness`; the console command and
Codex Plugin name are `harness`.

### Codex Plugin

The managed Plugin workflow documented here is part of `v0.2.1`. A personal
marketplace entry that points to this checkout still installs or refreshes the
Plugin separately from the Core package:

```bash
codex plugin add harness@personal
```

Codex caches Plugin contents. Start a new Codex task after installation or an
update so the refreshed Skills and metadata are loaded.

## Quick start

### 1. Configure checks

Create `.harness/checks.json`:

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

Checks are argv arrays, not shell command strings. `task create` resolves named
checks into the saved Task snapshot; `verify` later executes that saved
definition.

### 2. Create a Task

Create `task.json`:

```json
{
  "schema_version": 1,
  "id": "TASK-001",
  "type": "feature",
  "objective": "Add the requested behavior.",
  "scope": ["src", "tests"],
  "checks": ["unit-test"],
  "risk": "medium",
  "verifier": {
    "required": false
  }
}
```

Save the normalized Task snapshot and current full Git baseline:

```bash
harness task create --file task.json
harness task show TASK-001
```

### 3. Verify

After implementing the change:

```bash
harness verify TASK-001
```

Successful Evidence recording prints:

```json
{
  "evidence_path": "/path/to/repository/.harness/evidence/TASK-001/<RUN_ID>",
  "run_id": "<RUN_ID>"
}
```

`verify` returns success when it safely records Evidence, even if a required
check fails, times out, violates Scope, or changes product source. Those are
recorded failed outcomes. `complete` applies completion policy.

`verify --base-ref` is not supported. Verification uses only the full baseline
saved in the Task snapshot.

### Advanced and recovery operations

Export a portable review bundle:

```bash
harness verifier bundle TASK-001 \
  --run-id <RUN_ID> \
  --output <OUTPUT_DIR_OUTSIDE_REPOSITORY>
```

The bundle contains validated historical S0/S1 Evidence. It does not rerun
checks, execute a reviewer, collect current S2, create a Verdict, or complete
the Task. Keeping the output outside the target repository avoids changing
product source after verification.

Record and show a separately prepared Manual Verdict:

```bash
harness verifier record TASK-001 \
  --run-id <RUN_ID> \
  --file <VERDICT_JSON_OUTSIDE_REPOSITORY>

harness verifier show TASK-001 --run-id <RUN_ID>
```

Evaluate completion:

```bash
harness complete TASK-001 --run-id <RUN_ID>
```

Completion validates stored Evidence and any recorded Verdict, collects current
S2, requires S0 = S1 = S2, and then applies verifier, Scope, timeout, and
required-check gates.

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

Only `verification.json` uses schema version 2. Task, changed-files, checks, Run
Manifest, Source Snapshot, Bundle, Verdict, and Completion schemas retain their
existing versions.

Unsupported verification versions, missing files, tampering, or contradictory
stored data are Evidence errors (exit 8). Exit 9 is reserved for a valid v2 Run
whose source binding fails because S0 differs from S1 or S1 differs from S2.

## v0.1.x compatibility

Harness v0.2.x does not read v0.1.x verification Runs. Use the CLI from the
corresponding v0.1.x tag to read that Evidence. There is no in-place migration;
create a new Evidence v2 Run with a v0.2.x CLI for a source-bound completion
claim.

## Trust and security boundaries

- The Run Manifest detects missing or modified mechanical files by raw-byte
  size and SHA-256. It is not a signature or a defense against a local user who
  rewrites both Evidence and the manifest.
- Bundle export replaces known spellings of the current repository root and
  user home. Other POSIX, Windows, UNC, URL-like text and arbitrary check-output
  bytes are preserved. This is not general path anonymization or secret
  redaction.
- Check logs may contain sensitive values. Inspect a bundle before sharing it.
- `complete` validates saved check results; it does not rerun checks or redact
  secrets.
- Source binding is a local bounded observation. Harness does not lock the
  filesystem after S2 is collected or after `complete` returns.
- Recording a Manual Verdict binds it to a Task and Run; it does not establish
  that the reviewer was actually independent.
- Local Evidence is not an immutable central audit store, and v0.2.x does not
  claim support for every special Git state.
- Repository-local Codex credential policy is documented separately; it is not
  a Harness Core feature.

## Development verification

```bash
python3 scripts/sync_contracts.py --check
python3 -m unittest discover -s tests -v
python3 -m build
python3 -m twine check dist/*
python3 scripts/smoke_installed_cli.py --help
git diff --check
```

CI also builds and installs a wheel in a clean environment to verify the CLI,
public imports, and packaged contract resources.

## Documentation

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
- [v0.2.1 Release Notes](docs/releases/v0.2.1.md)
- [v0.2.0 Release Notes](docs/releases/v0.2.0.md)
- [v0.1.0 Release Notes](docs/releases/v0.1.0.md)
- [v0.1.1 Release Notes](docs/releases/v0.1.1.md)

## License

MIT License. See [LICENSE](LICENSE).
