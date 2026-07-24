# Harness repository instructions

## Core boundaries

- Inspect the relevant Core responsibility and call flow before changing it.
- Modify only the current dependency cone; prefer deletion over compatibility
  branches and do not perform repository-wide refactors automatically.
- Keep `validate_run()` as the single public authority for stored Run integrity.
- Do not reimplement stored Evidence interpretation in bundle, verdict, or
  completion consumers.
- Split a responsibility only when a concrete boundary and consumer require it.
- Do not add runtime dependencies without an explicit design reason.

## v0.2 contract

- Current Core supports source-bound verification Evidence v2 only.
- Preserve the public meaning of CLI commands, stdout JSON, stderr, stable exit
  codes, and Task, Evidence, Verdict, Bundle, and completion documents.
- Keep failed checks, timeouts, Scope violations, and source mismatch distinct
  from missing or corrupt Evidence.
- Do not add compatibility adapters, migration engines, new Schema versions,
  new commands, or roadmap features during the v0.2 scope freeze.
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
