"""Versioned, local integrity manifests for mechanical Evidence Runs.

This module owns only the byte-level manifest for one already-created Run.  It
does not collect Git state, execute checks, evaluate completion, or inspect
Verdicts.  A manifest identifies the mechanical files that existed when
``verify`` finished; it is not a signature, remote attestation, or immutable
storage mechanism.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from ._run_artifact_io import (
    RunArtifactPathError as _RunArtifactPathError,
    RunArtifactReadError as _RunArtifactReadError,
    read_run_artifact_bytes as _read_run_artifact_bytes,
    safe_run_relative_path as _safe_run_relative_path,
)


RUN_MANIFEST_FILENAME = "run-manifest.json"
RUN_MANIFEST_SCHEMA_VERSION = 1
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "task_id",
        "run_id",
        "files",
        "evidence_sha256",
        "created_at",
    }
)
_FILE_RECORD_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_SHA256_CHARACTERS = frozenset("0123456789abcdef")


class RunManifestError(ValueError):
    """Raised when a Run manifest or one of its files is unsafe or inconsistent."""


@dataclass(frozen=True)
class RunManifest:
    """One parsed and locally validated mechanical Evidence manifest."""

    document: dict[str, Any]
    path: Path
    evidence_sha256: str


def create_run_manifest(
    evidence_path: Path,
    *,
    task_id: str,
    run_id: str,
    evidence_files: Sequence[PurePosixPath],
) -> RunManifest:
    """Write the final manifest for one complete set of mechanical Evidence.

    Each file is read as raw bytes.  If any read, path validation, or write
    fails, no cleanup or recovery is attempted: the caller retains an
    incomplete Run that can be inspected or replaced by a new verification.
    """
    directory = _validated_evidence_directory(evidence_path)
    normalized_files = _normalized_expected_files(evidence_files)
    file_records = [_file_record(directory, relative_path) for relative_path in normalized_files]
    digest = _evidence_sha256(task_id, run_id, file_records)
    document: dict[str, Any] = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "task_id": task_id,
        "run_id": run_id,
        "files": file_records,
        "evidence_sha256": digest,
        "created_at": _utc_timestamp(),
    }
    manifest_path = directory / RUN_MANIFEST_FILENAME
    try:
        _atomic_write_json(manifest_path, document)
    except OSError as error:
        raise RunManifestError(
            f"Could not write {RUN_MANIFEST_FILENAME} for Evidence Run '{directory}': {error}."
        ) from error
    return RunManifest(document=document, path=manifest_path, evidence_sha256=digest)


def load_and_validate_run_manifest(
    evidence_path: Path,
    *,
    expected_task_id: str,
    expected_run_id: str,
    expected_files: Sequence[PurePosixPath],
) -> RunManifest:
    """Validate one manifest against its expected paths and current raw bytes."""
    directory = _validated_evidence_directory(evidence_path)
    normalized_expected = _normalized_expected_files(expected_files)
    manifest_path = directory / RUN_MANIFEST_FILENAME
    document = _read_manifest_document(directory, manifest_path)
    _validate_document_shape(document, manifest_path)

    if document["task_id"] != expected_task_id:
        raise RunManifestError(
            f"{RUN_MANIFEST_FILENAME} task_id does not match the requested Task id."
        )
    if document["run_id"] != expected_run_id:
        raise RunManifestError(
            f"{RUN_MANIFEST_FILENAME} run_id does not match the requested Run id."
        )

    records = _validated_file_records(document["files"], normalized_expected)
    for record in records:
        relative_path = _safe_evidence_relative_path(
            record["path"], f"{RUN_MANIFEST_FILENAME} file path"
        )
        contents = _read_evidence_bytes(directory, relative_path)
        actual_size = len(contents)
        if record["size_bytes"] != actual_size:
            raise RunManifestError(
                f"{RUN_MANIFEST_FILENAME} size mismatch for {relative_path.as_posix()}."
            )
        actual_sha256 = hashlib.sha256(contents).hexdigest()
        if record["sha256"] != actual_sha256:
            raise RunManifestError(
                f"{RUN_MANIFEST_FILENAME} hash mismatch for {relative_path.as_posix()}."
            )

    computed_digest = _evidence_sha256(expected_task_id, expected_run_id, records)
    if document["evidence_sha256"] != computed_digest:
        raise RunManifestError(
            f"{RUN_MANIFEST_FILENAME} evidence_sha256 does not match its file records."
        )
    return RunManifest(
        document=document,
        path=manifest_path,
        evidence_sha256=computed_digest,
    )


def _validated_evidence_directory(evidence_path: Path) -> Path:
    logical_path = Path(evidence_path)
    try:
        if logical_path.is_symlink() or not logical_path.is_dir():
            raise RunManifestError(
                f"Evidence Run directory is missing or unsafe: {logical_path}."
            )
        return logical_path.resolve(strict=True)
    except OSError as error:
        raise RunManifestError(
            f"Evidence Run directory is missing or unreadable: {logical_path}."
        ) from error


def _normalized_expected_files(
    evidence_files: Sequence[PurePosixPath],
) -> tuple[PurePosixPath, ...]:
    normalized: list[PurePosixPath] = []
    seen: set[str] = set()
    for index, value in enumerate(evidence_files):
        relative_path = _safe_evidence_relative_path(
            str(value), f"expected evidence file[{index}]"
        )
        normalized_path = relative_path.as_posix()
        if normalized_path == RUN_MANIFEST_FILENAME:
            raise RunManifestError(
                f"{RUN_MANIFEST_FILENAME} cannot include itself in its file records."
            )
        if normalized_path in seen:
            raise RunManifestError(
                f"expected evidence files duplicate '{normalized_path}'."
            )
        seen.add(normalized_path)
        normalized.append(relative_path)
    if not normalized:
        raise RunManifestError("Run manifest must contain at least one mechanical Evidence file.")
    return tuple(sorted(normalized, key=lambda path: path.as_posix()))


def _file_record(directory: Path, relative_path: PurePosixPath) -> dict[str, Any]:
    contents = _read_evidence_bytes(directory, relative_path)
    return {
        "path": relative_path.as_posix(),
        "size_bytes": len(contents),
        "sha256": hashlib.sha256(contents).hexdigest(),
    }


def _read_manifest_document(directory: Path, manifest_path: Path) -> dict[str, Any]:
    try:
        contents = _read_evidence_bytes(directory, PurePosixPath(RUN_MANIFEST_FILENAME))
    except RunManifestError as error:
        raise RunManifestError(
            f"{RUN_MANIFEST_FILENAME} is missing or unreadable for Evidence Run '{directory}'."
        ) from error
    try:
        value = json.loads(contents.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RunManifestError(f"{manifest_path} is not valid JSON.") from error
    if not isinstance(value, Mapping):
        raise RunManifestError(f"{manifest_path} must be a JSON object.")
    return dict(value)


def _validate_document_shape(document: Mapping[str, Any], manifest_path: Path) -> None:
    _require_exact_keys(document, _MANIFEST_FIELDS, str(manifest_path))
    if (
        type(document.get("schema_version")) is not int
        or document["schema_version"] != RUN_MANIFEST_SCHEMA_VERSION
    ):
        raise RunManifestError(f"{RUN_MANIFEST_FILENAME} has an unsupported schema_version.")
    for field in ("task_id", "run_id", "created_at"):
        if not isinstance(document.get(field), str) or not document[field]:
            raise RunManifestError(f"{RUN_MANIFEST_FILENAME} {field} must be a non-empty string.")
    if not isinstance(document.get("files"), list):
        raise RunManifestError(f"{RUN_MANIFEST_FILENAME} files must be an array.")
    if not _is_sha256(document.get("evidence_sha256")):
        raise RunManifestError(f"{RUN_MANIFEST_FILENAME} evidence_sha256 must be a SHA-256 hex value.")


def _validated_file_records(
    raw_records: list[object], expected_files: Sequence[PurePosixPath]
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    paths: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(raw_records):
        context = f"{RUN_MANIFEST_FILENAME} files[{index}]"
        if not isinstance(value, Mapping):
            raise RunManifestError(f"{context} must be an object.")
        _require_exact_keys(value, _FILE_RECORD_FIELDS, context)
        relative_path = _safe_evidence_relative_path(value.get("path"), f"{context}.path")
        normalized_path = relative_path.as_posix()
        if normalized_path in seen:
            raise RunManifestError(f"{context}.path duplicates '{normalized_path}'.")
        seen.add(normalized_path)
        size_bytes = value.get("size_bytes")
        if type(size_bytes) is not int or size_bytes < 0:
            raise RunManifestError(f"{context}.size_bytes must be a non-negative integer.")
        sha256 = value.get("sha256")
        if not _is_sha256(sha256):
            raise RunManifestError(f"{context}.sha256 must be a SHA-256 hex value.")
        paths.append(normalized_path)
        records.append(
            {"path": normalized_path, "size_bytes": size_bytes, "sha256": sha256}
        )

    expected_paths = [path.as_posix() for path in expected_files]
    if set(paths) != set(expected_paths):
        missing = sorted(set(expected_paths) - set(paths))
        if missing:
            raise RunManifestError(
                f"{RUN_MANIFEST_FILENAME} is missing {', '.join(missing)}."
            )
        unknown = sorted(set(paths) - set(expected_paths))
        raise RunManifestError(
            f"{RUN_MANIFEST_FILENAME} has unknown file record(s): {', '.join(unknown)}."
        )
    if paths != sorted(paths):
        raise RunManifestError(
            f"{RUN_MANIFEST_FILENAME} file records must be sorted by ascending path."
        )
    return records


def _read_evidence_bytes(directory: Path, relative_path: PurePosixPath) -> bytes:
    try:
        return _read_run_artifact_bytes(directory, relative_path)
    except _RunArtifactReadError as error:
        if error.reason == "missing":
            message = (
                f"Required Evidence file is missing: "
                f"{relative_path.as_posix()}."
            )
        elif error.reason == "unsafe":
            message = (
                f"Evidence file is unsafe or missing: "
                f"{relative_path.as_posix()}."
            )
        else:
            message = (
                f"Could not read Evidence file: "
                f"{relative_path.as_posix()}."
            )
        raise RunManifestError(message) from error


def _safe_evidence_relative_path(value: object, context: str) -> PurePosixPath:
    try:
        return _safe_run_relative_path(value, context)
    except _RunArtifactPathError as error:
        raise RunManifestError(str(error)) from error


def _evidence_sha256(
    task_id: str, run_id: str, file_records: Sequence[Mapping[str, Any]]
) -> str:
    payload = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "task_id": task_id,
        "run_id": run_id,
        "files": list(file_records),
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _require_exact_keys(value: Mapping[str, Any], expected: frozenset[str], context: str) -> None:
    missing = expected - set(value)
    unexpected = set(value) - expected
    if not missing and not unexpected:
        return
    details: list[str] = []
    if missing:
        details.append("missing " + ", ".join(sorted(missing)))
    if unexpected:
        details.append("unexpected " + ", ".join(sorted(unexpected)))
    raise RunManifestError(f"{context} has " + "; ".join(details) + " field(s).")


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in _SHA256_CHARACTERS for character in value)
    )


def _atomic_write_json(path: Path, value: object) -> None:
    contents = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    _atomic_write_bytes(path, f"{contents}\n".encode("utf-8"))


def _atomic_write_bytes(path: Path, value: bytes) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
