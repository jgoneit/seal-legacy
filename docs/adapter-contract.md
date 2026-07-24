# Harness Adapter CLI Contract

This document defines the public contract for a thin adapter, including the
Codex Plugin, when invoking the unreleased Harness Core `0.2.0.dev0` as a
subprocess. An adapter must not import the Core Python package; it uses only the
CLI and stdout JSON described below.

## Public CLI

| Command | Required arguments |
| --- | --- |
| `harness --version` | None |
| `harness task create` | `--file <TASK_JSON>` |
| `harness task show` | `<TASK_ID>` |
| `harness verify` | `<TASK_ID>` |
| `harness verifier bundle` | `<TASK_ID> --run-id <RUN_ID> --output <DIR>` |
| `harness verifier record` | `<TASK_ID> --run-id <RUN_ID> --file <VERDICT_JSON>` |
| `harness verifier show` | `<TASK_ID> --run-id <RUN_ID>` |
| `harness complete` | `<TASK_ID> --run-id <RUN_ID>` |

Current main does not support `verify --base-ref`, a hidden alias, or an
environment fallback. Supplying `--base-ref` is invalid argparse input and
returns exit 2. Verification always uses the full baseline commit saved in the
Task snapshot. Task baseline revision and CI-specific base/head selection are
separate, unsupported concerns.

## Success stdout

Except for `--version` and `--help`, successful stdout from every command above is a single UTF-8 JSON object. Diagnostic text is not appended to stdout JSON on success. Plain-text output from `--version` and `--help` is an intentional exception.

| Command | Required success JSON fields |
| --- | --- |
| `task create` | `schema_version`, `id`, `type`, `objective`, `scope`, `checks`, `risk`, `verifier`, `baseline` |
| `task show` | `schema_version`, `id`, `type`, `objective`, `scope`, `checks`, `risk`, `verifier`, `baseline` |
| `verify` | `run_id`, `evidence_path` |
| `verifier bundle` | `task_id`, `run_id`, `bundle_path`, `manifest_path`, `total_size_bytes`, `bundle_sha256` |
| `verifier record` | `task_id`, `run_id`, `raw_verdict_path`, `verdict_path` |
| `verifier show` | `schema_version`, `task_id`, `run_id`, `verifier`, `verdict`, `summary`, `findings`, `reviewed_at` |
| `complete` | `task_id`, `run_id`, `completion_path` |

Path fields may contain local absolute paths in the repository where the command ran. An adapter must treat them as opaque local paths and must not reuse them on another host or in another repository.

## stderr and exit codes

A successful result returns exit code `0` together with stdout JSON. A handled error writes `error: <message>` to stderr and does not mix success JSON into stdout. Input rejected by argparse—including forms that omit a required command or subcommand, such as `harness`, `harness task`, or `harness verifier`—must write usage text to stderr and return exit `2`. In this case, stdout contains no JSON.

An adapter must not assume that a failed command returns partial success JSON. In particular, if `verify` fails partway through, an evidence directory may remain, but the adapter must treat the nonzero exit as failure and must not consume stdout JSON as a result.

| Exit code | Meaning |
| ---: | --- |
| 0 | success |
| 2 | invalid input or schema |
| 3 | Git or repository error |
| 4 | scope violation at completion |
| 5 | required check failure at completion |
| 6 | required check timeout at completion |
| 7 | verifier gate not satisfied |
| 8 | evidence missing or corrupt |
| 9 | source binding not satisfied |

The existing meanings of these numbers are a stable contract. See [Exit codes](exit-codes.md) for the detailed completion decision order.

## Public read-only artifacts

An adapter's default boundary is the CLI and JSON. It may use the following
current-main read-only artifact surface only when it needs to display or archive
Evidence. An adapter must not create or modify these files.

| Location | Documented purpose and fields |
| --- | --- |
| `.harness/tasks/<TASK_ID>.json` | Task snapshot; the same Task JSON fields as `task create`/`task show` |
| `<evidence_path>/verification.json` | Source-bound Run identity and mechanical outcome using verification schema version 2 |
| `<evidence_path>/source-before-checks.json` | Required pre-check S0 product-source Snapshot using Source Snapshot schema version 1 |
| `<evidence_path>/source-after-checks.json` | Required post-check S1 product-source Snapshot using Source Snapshot schema version 1 |
| `<evidence_path>/run-manifest.json` | mechanical file records and local consistency identifier; `task_id`, `run_id`, `files`, `evidence_sha256` |
| `<evidence_path>/verdict.raw.json`, `verdict.json` | recorded original Manual Verdict and canonical snapshot |
| `<evidence_path>/completion.json` | Task/Run identity for successful completion and the consumed `evidence_sha256` |

Current Core supports verification schema version 2 only. Unsupported stored
verification versions are rejected with exit 8. The Task, changed-files,
checks, Run Manifest, Bundle, Verdict, Completion, and Source Snapshot document
schemas retain their existing versions.

A bundle includes S0 and S1 but remains historical: bundle creation does not
collect current S2, compare current source, rerun checks, or decide completion.

`changed-files.json`, `checks.json`, check logs, and `diff.patch` are preserved
as Evidence in the Run record above, but fields or internal representations not
listed in this document are not part of the adapter compatibility contract.
When portable review is needed, use `verifier bundle` instead of assembling
files directly from the filesystem.

## Unsupported dependencies

An adapter must not depend on any of the following:

- modules inside `src/harness` or direct Python imports
- private functions, Python exception classes, or undocumented dataclasses
- internal Git commands or subprocess implementations
- undocumented Evidence fields, temporary filenames, or atomic-write implementations
- test fixtures, repository-local prompt overrides, or editable installs from a development environment

This separation keeps Core's responsibility for deterministic local Evidence
distinct from an adapter's UI, model, network, credential, and retry policies.
Harness Core `0.2.0.dev0` does not call model APIs or external verifier CLIs.
No final `0.2.0` release artifact is published by this development contract.
See [Migrating verification Evidence to v0.2](migration-v0.2.md) for the
historical Evidence boundary.
