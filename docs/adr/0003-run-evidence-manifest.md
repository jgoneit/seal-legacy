# ADR 0003: Identify Mechanical Evidence with a Versioned Run Manifest

## Status

Accepted

## Context

The Run integrity validator checks that stored Tasks, check results, scope, and path relationships are mutually consistent. It did not, however, explicitly identify raw-byte changes or file replacements that semantic structure alone cannot detect, such as JSON whitespace, log output, or binary diffs.

Verifier Verdicts and completion are created by separate commands after verification. Mixing these files into the identity of mechanical Evidence at verification time would either create a circular hash or conflate artifacts created at different times under one contract.

## Decision

- Each new Run stores `run-manifest.json` as the final verification step after saving `verification.json`.
- The manifest includes `task.json`, `changed-files.json`, `diff.patch`, `checks.json`, `source-before-checks.json`, `source-after-checks.json`, `verification.json`, and every stdout and stderr log referenced by a recorded check.
- It excludes the manifest itself, `verdict.raw.json`, `verdict.json`, and `completion.json`.
- File records are ordered by ascending relative POSIX path, and each record contains the raw-byte `size_bytes` and SHA-256. No text normalization is performed.
- `evidence_sha256` is calculated by serializing only the schema version, Task ID, Run ID, and sorted file records as canonical JSON using UTF-8, `ensure_ascii=False`, sorted keys, and compact separators. `created_at` is excluded from the digest.
- `validate_run()` compares the expected mechanical file list, file records, actual raw-byte sizes, file SHA-256 values, and `evidence_sha256`. A Run without a manifest is rejected as incomplete Evidence.
- A bundle does not recalculate the validated Run's digest; it records that digest as `source_evidence_sha256`. Successful completion records the same value as `evidence_sha256`.

## Consequences

Because bundle creation, Verdict record/show, and completion pass through the existing canonical validator, they consistently reject the same manifest mismatch. A required-check failure, timeout, or Scope violation remains a validly stored failed Run when its manifest is accurate and remains available as input for external review.

The manifest is a local consistency identifier. It is not a signature, remote attestation, immutable storage, completion authority, or external trust anchor. It does not prevent an attack in which the same local user rewrites all Evidence and the manifest. When Harness encounters a mismatch, it does not automatically repair or roll back source or Evidence.

## Rejected alternatives

- Include Verdict and Completion in one manifest, creating circular-hash and temporal-ordering problems
- Hash only parsed JSON results or normalized text
- Add a self-hash or signature for the manifest to this local contract
- Add automatic repair, source rollback, or runtime hooks, approvals, and monitoring for manifest mismatches
- Introduce current-source snapshot binding in the same initial change

The manifest, Verdict, and Completion document schemas remain version 1.
