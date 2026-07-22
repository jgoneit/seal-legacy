# Outcome Harness v0.1.0 Release Scope

Language: English | [한국어](release-scope-v0.1.0.ko.md)

## Status

v0.1.0 is the first Experimental release of Outcome Harness. This version provides a CLI that verifies Evidence Run consistency and completion conditions locally. It does not claim production enforcement, cryptographic trust, or control over the Agent's work process.

A GitHub Release is created only when the `v0.1.0` tag is pushed. A regular push to `main` or adding this document alone does not publish a release.

## Included

- Task Spec validation, normalized snapshots, and Git baseline recording
- collection of Git changes based on Task scope and execution of argv-based checks
- storage of mechanical Evidence, including check stdout/stderr, exit codes, and timeouts
- canonical Verdict Schema and runtime validation
- canonical Run Integrity Validator and Run Evidence Manifest
- local consistency checks for mechanical Evidence based on raw-byte digests and `evidence_sha256`
- portable verifier bundle creation
- Manual Verdict record/show and fail-closed completion
- stable CLI exit codes and GitHub Actions CI
- a clean-install validation path that verifies the CLI and packaged resources after wheel installation

## Explicitly Not Included

- Pre/Post-check Source Snapshots or current-source binding after verification
- removal of `--base-ref`
- cryptographic signatures, remote attestation, an immutable ledger, or immutable storage
- complete secret redaction
- Multimodal Evidence
- external verifier adapters, model APIs, or calls to external verifier CLIs
- runtime hooks, approval tokens, an Agent state machine, or automatic verify/complete/repair
- worktree orchestration or control of subagent topology

## Trust Boundary

Within the local filesystem, v0.1.0 verifies the existence, identity, raw-byte digests, and mutual consistency of stored mechanical Evidence. `run-manifest.json` and `evidence_sha256` identify this local consistency, but they do not provide cryptographic provenance, completion authority, a remote trust anchor, or tamper-proof storage.

`harness complete` reads only stored Run Evidence. It does not rerun checks, recollect the Git diff, or compare whether the current source has changed since verification.

## Known Limitations

- `complete` cannot detect source changes made after verification.
- `verify --base-ref` can override the Task snapshot baseline for that Run only.
- It cannot prevent an attack in which the same local user recalculates and changes both Evidence and the manifest.
- There is no signature, remote attestation, or immutable storage.
- Secret redaction is incomplete, and a person must review check logs and bundles before sharing them.

These limitations are published constraints of the v0.1.0 Experimental release and are not release blockers.

## Compatibility

- Python 3.11 and later are supported.
- The public CLI and stable exit codes follow the [Adapter CLI Contract](adapter-contract.md).
- JSON fields and the read-only `.harness` artifact surface that an adapter may depend on are limited to the same contract.
- Python modules, dataclasses, private functions, and Git implementation details in `src/harness` are not part of the compatibility surface.

## Upgrade Direction

A later version will add source binding as a separate Run integrity feature and then revisit the `--base-ref` policy. Multimodal Evidence and an optional external adapter are separate scopes that follow afterward. The trust boundary of v0.1.0 must not be interpreted as if it already provides these later features.
