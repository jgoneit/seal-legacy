# ADR 0004: Identify Final Product Source with a Canonical Snapshot

## Status

Accepted

## Context

Harness records a Task baseline commit and can collect layered committed,
staged, unstaged, and untracked change metadata. Those layers are useful
Evidence, but they do not provide one identity for the final product source
represented by the current Working Tree. Moving unchanged bytes from unstaged
to staged or from staged to committed must not change that identity.

The source calculation is independent from verification persistence and
completion policy. Scope enforcement remains a separate mechanical policy, so
source identity must include product changes outside the Task Scope.

## Decision

- `collect_source_snapshot(task, *, cwd=None)` is the single read-only
  collection API. It uses only the saved Task baseline and does not accept
  `--base-ref` or another override.
- The baseline is resolved to a full commit object ID. Candidate paths combine
  its complete tree, one baseline-to-final-Working-Tree Git comparison, current
  tracked paths, and current non-ignored untracked paths. Git index hints and
  conversion settings such as `assume-unchanged`, `skip-worktree`,
  `core.filemode`, and clean filters are not source-byte authority. Harness
  reads the actual supported Working Tree node and compares its raw bytes and
  normalized mode with the baseline blob so index-only intermediate states do
  not leak into the result.
- Current Git ignore rules exclude untracked paths. The canonical Harness
  metadata predicate excludes Task, Evidence, runs, lessons, and config
  metadata, including metadata-only unmerged index paths. Product files outside
  Scope remain included, and an unmerged product path still fails closed.
- Entries are ordered by repository-relative Git path bytes. A present entry
  records normalized mode, raw-byte size, and SHA-256; a deleted entry records
  null mode, size, and hash. Renames are represented as deletion of the old path
  and presence of the new path. Directories are containers rather than entries;
  only their supported descendant source nodes participate.
- Regular files use mode `100644` or `100755` and are hashed in bounded chunks.
  On POSIX, `100755` follows Git by requiring the owner-execute bit; group or
  other execute bits do not change Snapshot identity. Symlinks use mode
  `120000`; Harness hashes the link-target bytes without following the target,
  including absolute, external, broken, or repository-relative targets.
- Gitlinks/submodules, FIFOs, sockets, devices, and other unsupported source
  nodes fail with `SourceSnapshotError`. Static parent symlinks are not followed
  while reading nested paths.
- Collection performs two bounded semantic observations. Private stat
  fingerprints cover every observed product-source node but are excluded from
  entries and the digest. A file identity, size, timestamp, type, or final entry
  mismatch fails without automatic retry.
- `snapshot_sha256` hashes canonical JSON containing only schema version 1, the
  full baseline, and sorted entries. Serialization uses ASCII-safe escaping,
  sorted keys, and compact separators. The digest excludes itself and contains
  no timestamp, absolute path, or source file body.

## Consequences

The same baseline and final source produce the same digest across unstaged,
staged, and committed transitions. Content, path, normalized executable mode,
symlink target, or binary byte changes change the Snapshot. The baseline itself
remains part of the identity even when two commits contain the same tree.

The filesystem is not a transactional snapshot service. The bounded double
observation and file-descriptor checks detect supported concurrent changes but
do not claim hostile-kernel or remote-filesystem atomicity.

The collector itself does not save artifacts, run checks, change CLI output, or
apply completion policy. The digest is a local deterministic identifier, not a
signature, remote attestation, cryptographic provenance, or external trust
anchor. [ADR 0005](0005-verify-complete-source-binding.md) uses the unchanged
collector for S0, S1, and S2.

## Rejected alternatives

- Hash `HEAD`, the index, or the sequence of Git layers as source identity
- Restrict the Snapshot to Task Scope
- Follow symlinks and hash target file contents
- Reject every symlink instead of preserving Git's `120000` blob semantics
- Store complete source file bodies in the Snapshot
- Add a generic repository, provider, signing, CI, or remote-attestation layer
- Couple verify, Evidence, `validate_run()`, bundle, or completion directly to
  collector internals
