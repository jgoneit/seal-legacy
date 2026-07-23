"""Deterministic, baseline-relative snapshots of the current product source.

This module reads Git and the working tree only.  It does not run checks, write
Evidence, create bundles, evaluate completion, or accept a baseline override.
The resulting digest is a local source identifier, not a signature or external
trust anchor.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ._path_policy import is_harness_metadata_path
from .gitdiff import (
    GitDiffError,
    _FinalTreeCandidate,
    _collect_final_tree_candidates,
    _is_git_ignored,
)


SOURCE_SNAPSHOT_SCHEMA_VERSION = 1
SOURCE_HASH_CHUNK_SIZE = 1024 * 1024
_REGULAR_MODES = frozenset({"100644", "100755"})
_SUPPORTED_MODES = frozenset({*_REGULAR_MODES, "120000"})


class SourceSnapshotError(RuntimeError):
    """Raised when a stable, supported source snapshot cannot be collected."""


@dataclass(frozen=True)
class SourceSnapshotEntry:
    """One canonical baseline-relative source entry."""

    path: str
    state: Literal["present", "deleted"]
    mode: str | None
    size_bytes: int | None
    sha256: str | None

    def to_document(self) -> dict[str, Any]:
        """Return the portable JSON representation of this immutable entry."""
        return {
            "path": self.path,
            "state": self.state,
            "mode": self.mode,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class SourceSnapshot:
    """One deterministic view of product source relative to a Task baseline."""

    schema_version: int
    baseline: str
    entries: tuple[SourceSnapshotEntry, ...]
    snapshot_sha256: str

    def to_document(self) -> dict[str, Any]:
        """Return a new JSON-compatible document without exposing mutable state."""
        return {
            "schema_version": self.schema_version,
            "baseline": self.baseline,
            "entries": [entry.to_document() for entry in self.entries],
            "snapshot_sha256": self.snapshot_sha256,
        }


@dataclass(frozen=True)
class _ObservedSource:
    mode: str
    size_bytes: int
    sha256: str
    fingerprint: tuple[int, int, int, int, int, int, int]


@dataclass(frozen=True)
class _SnapshotObservation:
    baseline: str
    entries: tuple[SourceSnapshotEntry, ...]
    source_fingerprints: tuple[
        tuple[str, tuple[int, int, int, int, int, int, int]],
        ...,
    ]


def collect_source_snapshot(
    task: Mapping[str, object],
    *,
    cwd: str | Path | None = None,
) -> SourceSnapshot:
    """Collect a stable source snapshot from the Task's saved baseline.

    Collection is intentionally observed twice.  The second bounded pass is
    compared with the first and is not retried: disagreement means the source
    was not stable enough to identify safely.
    """
    try:
        first = _collect_snapshot_observation(task, cwd=cwd)
        second = _collect_snapshot_observation(task, cwd=cwd)
    except SourceSnapshotError:
        raise
    except GitDiffError as error:
        raise SourceSnapshotError(str(error)) from error

    if first != second:
        raise SourceSnapshotError(
            "Product source changed while the source snapshot was being collected."
        )

    payload = _snapshot_payload(second.baseline, second.entries)
    digest = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    return SourceSnapshot(
        schema_version=SOURCE_SNAPSHOT_SCHEMA_VERSION,
        baseline=second.baseline,
        entries=second.entries,
        snapshot_sha256=digest,
    )


def _collect_snapshot_observation(
    task: Mapping[str, object],
    *,
    cwd: str | Path | None,
) -> _SnapshotObservation:
    candidate_set = _collect_final_tree_candidates(task, cwd=cwd)
    product_gitlinks = [
        path
        for path in candidate_set.gitlink_paths
        if not is_harness_metadata_path(path)
    ]
    if product_gitlinks:
        raise SourceSnapshotError(
            f"Unsupported Git submodule path: {product_gitlinks[0]}."
        )

    candidates = {candidate.path: candidate for candidate in candidate_set.candidates}
    for path in _discover_nonregular_source_paths(candidate_set.repository):
        if path in candidate_set.tracked_paths and path not in candidates:
            continue
        previous = candidates.get(path)
        if previous is None:
            candidates[path] = _FinalTreeCandidate(
                path=path,
                baseline_mode=None,
                baseline_oid=None,
                current_present=True,
                current_mode=None,
            )
        elif not previous.current_present:
            candidates[path] = _FinalTreeCandidate(
                path=path,
                baseline_mode=previous.baseline_mode,
                baseline_oid=previous.baseline_oid,
                current_present=True,
                current_mode=None,
            )

    entries: list[SourceSnapshotEntry] = []
    source_fingerprints: list[
        tuple[str, tuple[int, int, int, int, int, int, int]]
    ] = []
    for path in sorted(candidates, key=_path_sort_key):
        candidate = candidates[path]
        if is_harness_metadata_path(candidate.path):
            continue
        _validate_candidate_modes(candidate)
        observed = (
            _observe_current_source(candidate_set.repository, candidate)
            if candidate.current_present
            else None
        )
        if observed is None:
            if candidate.baseline_mode is not None:
                entries.append(
                    SourceSnapshotEntry(
                        path=candidate.path,
                        state="deleted",
                        mode=None,
                        size_bytes=None,
                        sha256=None,
                    )
                )
            continue

        source_fingerprints.append((candidate.path, observed.fingerprint))
        if candidate.baseline_mode is not None:
            if candidate.baseline_oid is None:
                raise SourceSnapshotError(
                    f"Git baseline metadata is missing for '{candidate.path}'."
                )
            baseline_size, baseline_sha256 = _hash_git_blob(
                candidate_set.repository,
                candidate.baseline_oid,
            )
            if (
                observed.mode == candidate.baseline_mode
                and observed.size_bytes == baseline_size
                and observed.sha256 == baseline_sha256
            ):
                continue

        entries.append(
            SourceSnapshotEntry(
                path=candidate.path,
                state="present",
                mode=observed.mode,
                size_bytes=observed.size_bytes,
                sha256=observed.sha256,
            )
        )

    entries.sort(key=lambda entry: _path_sort_key(entry.path))
    return _SnapshotObservation(
        baseline=candidate_set.baseline,
        entries=tuple(entries),
        source_fingerprints=tuple(source_fingerprints),
    )


def _discover_nonregular_source_paths(repository: Path) -> tuple[str, ...]:
    """Find unsupported nodes that Git's untracked list can omit."""
    discovered: list[str] = []
    pending: list[tuple[Path, tuple[str, ...]]] = [(repository, ())]
    while pending:
        directory, prefix = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(
                    iterator,
                    key=lambda entry: os.fsencode(entry.name),
                )
        except OSError as error:
            raise SourceSnapshotError(
                f"Could not scan source directory '{directory}': {error}."
            ) from error

        for entry in entries:
            parts = (*prefix, entry.name)
            relative_path = "/".join(parts)
            if not prefix and entry.name == ".git":
                continue
            if is_harness_metadata_path(relative_path):
                continue

            try:
                source_stat = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise SourceSnapshotError(
                    f"Could not inspect source path '{relative_path}': {error}."
                ) from error

            is_symlink = stat.S_ISLNK(source_stat.st_mode)
            is_regular = stat.S_ISREG(source_stat.st_mode)
            is_reparse_point = _is_windows_reparse_point(source_stat)
            is_directory = (
                stat.S_ISDIR(source_stat.st_mode)
                and not is_reparse_point
            )
            if is_directory:
                if not _is_git_ignored(repository, relative_path):
                    pending.append((Path(entry.path), parts))
                continue
            if is_regular or is_symlink:
                continue
            if not _is_git_ignored(repository, relative_path):
                discovered.append(relative_path)

    return tuple(sorted(discovered, key=_path_sort_key))


def _validate_candidate_modes(candidate: _FinalTreeCandidate) -> None:
    for label, mode in (
        ("baseline", candidate.baseline_mode),
        ("current", candidate.current_mode),
    ):
        if mode is not None and mode not in _SUPPORTED_MODES:
            raise SourceSnapshotError(
                f"Unsupported {label} Git mode '{mode}' for '{candidate.path}'."
            )


def _observe_current_source(
    repository: Path,
    candidate: _FinalTreeCandidate,
) -> _ObservedSource | None:
    parts = _portable_path_parts(candidate.path)
    if _supports_directory_descriptors():
        return _observe_with_directory_descriptor(repository, parts, candidate)
    return _observe_with_path(repository, parts, candidate)


def _observe_with_directory_descriptor(
    repository: Path,
    parts: tuple[str, ...],
    candidate: _FinalTreeCandidate,
) -> _ObservedSource | None:
    parent_descriptor = _open_parent_descriptor(repository, parts[:-1])
    if parent_descriptor is None:
        return None
    try:
        name = parts[-1]
        try:
            before = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise SourceSnapshotError(
                f"Could not inspect source path '{candidate.path}': {error}."
            ) from error

        if stat.S_ISLNK(before.st_mode):
            return _observe_symlink_at(
                parent_descriptor,
                name,
                before,
                candidate,
            )
        if _is_windows_reparse_point(before):
            raise SourceSnapshotError(
                f"Unsupported Windows reparse point at '{candidate.path}'."
            )
        if stat.S_ISREG(before.st_mode):
            return _observe_regular_at(
                parent_descriptor,
                name,
                before,
                candidate,
            )
        if stat.S_ISDIR(before.st_mode):
            return None
        raise _unsupported_file_type(candidate.path, before.st_mode)
    finally:
        os.close(parent_descriptor)


def _open_parent_descriptor(
    repository: Path,
    components: tuple[str, ...],
) -> int | None:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        descriptor = os.open(repository, flags)
    except OSError as error:
        raise SourceSnapshotError(
            f"Could not open source repository '{repository}': {error}."
        ) from error

    for component in components:
        try:
            child = os.open(component, flags, dir_fd=descriptor)
        except OSError as error:
            os.close(descriptor)
            if error.errno in {
                errno.ENOENT,
                errno.ENOTDIR,
                errno.ELOOP,
            }:
                return None
            raise SourceSnapshotError(
                f"Could not inspect a parent directory for source path: {error}."
            ) from error
        os.close(descriptor)
        descriptor = child
    return descriptor


def _observe_symlink_at(
    parent_descriptor: int,
    name: str,
    before: os.stat_result,
    candidate: _FinalTreeCandidate,
) -> _ObservedSource:
    try:
        target = os.readlink(name, dir_fd=parent_descriptor)
        after = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError as error:
        raise SourceSnapshotError(
            f"Could not read symlink source path '{candidate.path}': {error}."
        ) from error
    if _stat_fingerprint(before) != _stat_fingerprint(after):
        raise SourceSnapshotError(
            f"Source path '{candidate.path}' changed while it was being hashed."
        )
    target_bytes = os.fsencode(target)
    return _ObservedSource(
        mode="120000",
        size_bytes=len(target_bytes),
        sha256=hashlib.sha256(target_bytes).hexdigest(),
        fingerprint=_stat_fingerprint(after),
    )


def _observe_regular_at(
    parent_descriptor: int,
    name: str,
    before: os.stat_result,
    candidate: _FinalTreeCandidate,
) -> _ObservedSource:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    except OSError as error:
        raise SourceSnapshotError(
            f"Could not open source file '{candidate.path}': {error}."
        ) from error
    try:
        return _hash_open_regular_file(
            descriptor,
            before,
            candidate,
            post_stat=lambda: os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            ),
        )
    finally:
        os.close(descriptor)


def _observe_with_path(
    repository: Path,
    parts: tuple[str, ...],
    candidate: _FinalTreeCandidate,
) -> _ObservedSource | None:
    current = repository
    for component in parts[:-1]:
        current = current / component
        try:
            parent_stat = os.lstat(current)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise SourceSnapshotError(
                f"Could not inspect a parent of '{candidate.path}': {error}."
            ) from error
        if (
            stat.S_ISLNK(parent_stat.st_mode)
            or _is_windows_reparse_point(parent_stat)
            or not stat.S_ISDIR(parent_stat.st_mode)
        ):
            return None

    path = current / parts[-1]
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise SourceSnapshotError(
            f"Could not inspect source path '{candidate.path}': {error}."
        ) from error

    if stat.S_ISLNK(before.st_mode):
        try:
            target = os.readlink(path)
            after = os.lstat(path)
        except OSError as error:
            raise SourceSnapshotError(
                f"Could not read symlink source path '{candidate.path}': {error}."
            ) from error
        if _stat_fingerprint(before) != _stat_fingerprint(after):
            raise SourceSnapshotError(
                f"Source path '{candidate.path}' changed while it was being hashed."
            )
        target_bytes = os.fsencode(target)
        return _ObservedSource(
            mode="120000",
            size_bytes=len(target_bytes),
            sha256=hashlib.sha256(target_bytes).hexdigest(),
            fingerprint=_stat_fingerprint(after),
        )

    if _is_windows_reparse_point(before):
        raise SourceSnapshotError(
            f"Unsupported Windows reparse point at '{candidate.path}'."
        )
    if stat.S_ISDIR(before.st_mode):
        return None
    if not stat.S_ISREG(before.st_mode):
        raise _unsupported_file_type(candidate.path, before.st_mode)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise SourceSnapshotError(
            f"Could not open source file '{candidate.path}': {error}."
        ) from error
    try:
        return _hash_open_regular_file(
            descriptor,
            before,
            candidate,
            post_stat=lambda: os.lstat(path),
        )
    finally:
        os.close(descriptor)


def _hash_open_regular_file(
    descriptor: int,
    before: os.stat_result,
    candidate: _FinalTreeCandidate,
    *,
    post_stat,
) -> _ObservedSource:
    try:
        opened = os.fstat(descriptor)
        if _stat_fingerprint(before) != _stat_fingerprint(opened):
            raise SourceSnapshotError(
                f"Source path '{candidate.path}' changed before it could be hashed."
            )
        size_bytes, sha256 = _hash_file_descriptor(descriptor)
        after_open = os.fstat(descriptor)
        after_path = post_stat()
    except SourceSnapshotError:
        raise
    except OSError as error:
        raise SourceSnapshotError(
            f"Could not hash source file '{candidate.path}': {error}."
        ) from error

    fingerprint = _stat_fingerprint(before)
    if (
        fingerprint != _stat_fingerprint(after_open)
        or fingerprint != _stat_fingerprint(after_path)
        or size_bytes != before.st_size
    ):
        raise SourceSnapshotError(
            f"Source path '{candidate.path}' changed while it was being hashed."
        )
    return _ObservedSource(
        mode=_regular_mode(before, candidate),
        size_bytes=size_bytes,
        sha256=sha256,
        fingerprint=fingerprint,
    )


def _hash_file_descriptor(descriptor: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    size_bytes = 0
    while True:
        chunk = _read_hash_chunk(descriptor)
        if not chunk:
            break
        digest.update(chunk)
        size_bytes += len(chunk)
    return size_bytes, digest.hexdigest()


def _read_hash_chunk(descriptor: int) -> bytes:
    return os.read(descriptor, SOURCE_HASH_CHUNK_SIZE)


def _hash_git_blob(repository: Path, object_id: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    size_bytes = 0
    try:
        with tempfile.TemporaryFile(mode="w+b") as stderr:
            process = subprocess.Popen(
                ["git", "-C", str(repository), "cat-file", "blob", object_id],
                stdout=subprocess.PIPE,
                stderr=stderr,
            )
            if process.stdout is None:
                process.kill()
                process.wait()
                raise SourceSnapshotError("Git did not provide baseline blob output.")
            try:
                while True:
                    chunk = process.stdout.read(SOURCE_HASH_CHUNK_SIZE)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size_bytes += len(chunk)
            except OSError as error:
                process.kill()
                process.wait()
                raise SourceSnapshotError(
                    f"Could not read Git baseline blob '{object_id}': {error}."
                ) from error
            finally:
                process.stdout.close()

            returncode = process.wait()
            if returncode != 0:
                stderr.seek(0)
                detail = stderr.read(8192).decode("utf-8", "replace").strip()
                raise SourceSnapshotError(
                    detail
                    or f"Git could not read baseline blob '{object_id}'."
                )
    except OSError as error:
        raise SourceSnapshotError(
            "Git is required to collect a source snapshot."
        ) from error
    return size_bytes, digest.hexdigest()


def _regular_mode(
    source_stat: os.stat_result,
    candidate: _FinalTreeCandidate,
) -> str:
    if os.name != "nt":
        return "100755" if source_stat.st_mode & 0o111 else "100644"
    if (
        candidate.current_mode == "120000"
        or (
            candidate.current_mode is None
            and candidate.baseline_mode == "120000"
        )
    ):
        return "120000"
    if candidate.current_mode in _REGULAR_MODES:
        return candidate.current_mode
    if candidate.baseline_mode in _REGULAR_MODES:
        return candidate.baseline_mode
    return "100644"


def _portable_path_parts(path: str) -> tuple[str, ...]:
    if (
        not path
        or "\0" in path
        or path.startswith("/")
        or (os.name == "nt" and len(path) >= 2 and path[1] == ":")
    ):
        raise SourceSnapshotError(
            f"Git source path must be repository-relative and portable: {path!r}."
        )
    parts = tuple(path.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise SourceSnapshotError(
            f"Git source path is not canonical and portable: {path!r}."
        )
    return parts


def _supports_directory_descriptors() -> bool:
    return (
        os.name == "posix"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.readlink in os.supports_dir_fd
    )


def _stat_fingerprint(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_mode,
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_nlink,
    )


def _is_windows_reparse_point(value: os.stat_result) -> bool:
    return bool(getattr(value, "st_file_attributes", 0) & 0x400)


def _unsupported_file_type(path: str, file_mode: int) -> SourceSnapshotError:
    if stat.S_ISFIFO(file_mode):
        kind = "FIFO"
    elif stat.S_ISSOCK(file_mode):
        kind = "socket"
    elif stat.S_ISCHR(file_mode):
        kind = "character device"
    elif stat.S_ISBLK(file_mode):
        kind = "block device"
    elif stat.S_ISDIR(file_mode):
        kind = "directory"
    else:
        kind = "special file"
    return SourceSnapshotError(
        f"Unsupported source file type at '{path}': {kind}."
    )


def _snapshot_payload(
    baseline: str,
    entries: tuple[SourceSnapshotEntry, ...],
) -> dict[str, Any]:
    return {
        "schema_version": SOURCE_SNAPSHOT_SCHEMA_VERSION,
        "baseline": baseline,
        "entries": [entry.to_document() for entry in entries],
    }


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _path_sort_key(path: str) -> bytes:
    return path.encode("utf-8", "surrogateescape")
