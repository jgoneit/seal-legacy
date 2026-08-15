# ADR 0001: Use the Verdict Schema as the Canonical Contract

## Status

Accepted

## Context

If the public JSON Schema for Manual Verdicts, the verifier prompt, and a hand-written Python validator define different structures, the same Seal Legacy Core (Python) version may produce or accept different Verdicts across environments. In particular, if the prompt instructs a reviewer to use verdict values or finding fields that differ from the Schema, the runtime may reject JSON that appears valid to the person reviewing the bundle.

Verdicts are also used in installed-package environments, so arbitrary files from the source tree or repository-specific prompt overrides cannot serve as the runtime contract. Structural validation should be performed by the public Schema rather than by repetitive Python conditionals.

## Decision

- Keep `schemas/verdict.schema.json` and `prompts/verifier.md` at the repository root as human-edited canonical sources.
- Treat the Verdict Schema and prompt in `src/seal_legacy/resources` as generated mirrors; `scripts/sync_contracts.py` and CI verify byte-for-byte synchronization.
- At runtime, read the packaged Verdict Schema through `importlib.resources` and validate structure and formats with a Draft 2020-12 validator and `FormatChecker`.
- Remove the hand-written Python structural validator, enum lists, exact-key checks, and timestamp-format checks.
- After Schema validation, the validator performs only expected-identity checks as contextual validation to bind the Verdict to a specific Task and run.
- Validate the complete JSON example in the verifier prompt with the actual validator.
- Bundles use only the verifier instructions from the package resource. Repository-specific prompt overrides are not currently supported.

## Consequences

A single JSON Schema determines Verdict fields, enums, types, unknown-property policy, minimum lengths, and date-time formats. The runtime must provide `jsonschema` and an RFC 3339 format-checker implementation as dependencies, and package data must include the Schema resource.

The public CLI forms of `record` and `show` and the filenames `verdict.raw.json` and `verdict.json` remain unchanged. `verdict.py` focuses on file I/O, raw preservation, atomic snapshot storage, revalidation of stored raw data and snapshots, semantic-equivalence comparison, and finding-count calculation.

This decision does not introduce a full Run integrity validator. Evidence manifests, digests, snapshot binding, external verifier execution, automatic fallback, and attestation are outside the scope of this ADR.

## Rejected alternatives

- Keep the Python validator as the canonical source
- Keep the Schema as test-only documentation
- Allow unrestricted repository prompt overrides
- Manage the Schema and prompt independently
