# Seal Legacy repository instructions

## Core boundaries

- Inspect the relevant Core responsibility and call flow before changing it.
- Modify only the current dependency cone; prefer deletion over compatibility
  branches and do not perform repository-wide refactors automatically.
- Keep `validate_run()` as the single public authority for stored Run integrity.
- Do not reimplement stored Evidence interpretation in bundle, verdict, or
  completion consumers.
- Split a responsibility only when a concrete boundary and consumer require it.
- Do not add runtime dependencies without an explicit design reason.

## v0.3 development contract

- The current Core development line is `0.3.0.dev0`; the published v0.2
  contract remains historical release material.
- Current Core continues to support source-bound verification Evidence v2 only.
- Preserve the public meaning of CLI commands, stdout JSON, stderr, stable exit
  codes, and Task, Evidence, Verdict, Bundle, and completion documents.
- Keep failed checks, timeouts, Scope violations, and source mismatch distinct
  from missing or corrupt Evidence.
- New read-only state surfaces must consume `ValidatedRun` from `validate_run()`;
  they must not reinterpret persisted Evidence or imply lifecycle transitions.
- Do not add compatibility adapters, migration engines, persisted Schema
  versions, or commands outside the approved v0.3 dependency cone.
- Bundle exports a validated stored Run; it does not rerun checks or collect S2.

## Change protocol

- Preserve existing dirty changes and do not mix unrelated cleanup.
- Add characterization coverage before structural changes unless existing tests
  already protect the behavior.
- Protect identity, path, digest, failure, and source-binding boundaries.
- Name the canonical implementation before deleting duplication or dead code.
- Do not split large modules or add abstractions only to reduce line counts.

## Verification

- Run focused tests while changing the dependency cone.
- Before completion, run the full unittest suite, contract sync check, and
  `git diff --check`.
- Build the wheel, inspect package contents, run `twine check`, and smoke-test
  the installed CLI, public imports, and packaged resources in a clean
  environment.
- Record commands that were not run and any remaining risk.

## Coordination and documentation

- Codex decides whether independent read-heavy work benefits from SubAgents; do
  not require a fixed role, count, sequence, or topology.
- The Main Agent owns final writes, integration, and verification.
- Review architecture, ADR, exit-code, and adapter documentation when their
  authority changes.
- Keep README English/Korean pairs; keep technical documentation canonical in
  English and preserve historical release notes as historical material.
- Do not document unimplemented behavior as a current contract.
