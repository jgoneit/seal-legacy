"""In-memory Git change collection and Task Scope classification.

This module deliberately collects only change metadata.  It does not execute
Task checks, write evidence, expose a CLI command, or retain file contents.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


# These paths describe Harness's own records rather than product changes.  They
# are retained in ``ChangeCollection.changes`` for observability, but excluded
# from ``ChangeCollection.product_changes`` and scope results.
HARNESS_METADATA_DIRECTORIES = (
    ".harness/tasks",
    ".harness/evidence",
)
HARNESS_METADATA_FILES = frozenset(
    {
        ".harness/runs.jsonl",
        ".harness/lessons.md",
        ".harness/config.json",
    }
)


class GitDiffError(RuntimeError):
    """Base error for Git change collection."""


class GitDiffRepositoryError(GitDiffError):
    """Raised when change collection is requested outside a Git repository."""


class GitDiffReferenceError(GitDiffError):
    """Raised when the selected baseline cannot be resolved to a commit."""


class GitDiffTaskError(GitDiffError):
    """Raised when the supplied in-memory Task data lacks a usable baseline or scope."""


@dataclass(frozen=True)
class FileChange:
    """Metadata for one change in one Git layer.

    ``path`` is the current path when one exists, otherwise the deleted path.
    For renames and copies, ``previous_path`` holds the original path.  No file
    contents or patches are retained; a binary change is represented only by
    ``is_binary=True``.
    """

    source: str
    status: str
    path: str
    previous_path: str | None
    old_mode: str | None
    new_mode: str | None
    mode_changed: bool
    is_binary: bool
    in_scope: bool


@dataclass(frozen=True)
class ChangeCollection:
    """All collected changes plus product-only Scope classification."""

    base_ref: str
    scope: tuple[str, ...]
    changes: tuple[FileChange, ...]
    metadata_changes: tuple[FileChange, ...]
    product_changes: tuple[FileChange, ...]
    in_scope_changes: tuple[FileChange, ...]
    out_of_scope_changes: tuple[FileChange, ...]

    @property
    def scope_passed(self) -> bool:
        """Whether every product change is within the Task Scope."""
        return not self.out_of_scope_changes


@dataclass(frozen=True)
class _RawDiffEntry:
    """One parsed record from ``git diff --raw -z``."""

    git_status: str
    old_path: str | None
    new_path: str | None
    old_mode: str | None
    new_mode: str | None


def collect_changes(
    task: Mapping[str, object],
    *,
    cwd: str | Path | None = None,
    base_ref: str | None = None,
) -> ChangeCollection:
    """Collect changes from a Task baseline (or explicit base ref) in memory.

    The Task mapping must contain ``baseline`` and ``scope`` fields from a
    normalized Task snapshot.  ``base_ref`` takes precedence over ``baseline``
    so that a future CLI ``--base-ref`` option can reuse this internal API.

    The result preserves separate committed, staged, unstaged, and untracked
    layers.  It never runs Task checks or writes files.
    """
    repository = find_repository_root(cwd)
    scope = _task_scope(task)
    resolved_base_ref = _resolve_task_base_ref(repository, task, base_ref)

    changes: list[FileChange] = []
    for source in ("committed", "staged", "unstaged"):
        for entry, is_binary in _tracked_changes(repository, source, resolved_base_ref):
            changes.append(_to_file_change(entry, source, is_binary, scope))

    for path in _untracked_paths(repository):
        changes.append(
            FileChange(
                source="untracked",
                status="untracked",
                path=path,
                previous_path=None,
                old_mode=None,
                new_mode=None,
                mode_changed=False,
                is_binary=_is_untracked_binary(repository, path),
                in_scope=_paths_match_scope((path,), scope),
            )
        )

    metadata_changes = tuple(change for change in changes if _is_metadata_change(change))
    product_changes = tuple(change for change in changes if not _is_metadata_change(change))
    in_scope_changes = tuple(change for change in product_changes if change.in_scope)
    out_of_scope_changes = tuple(change for change in product_changes if not change.in_scope)

    return ChangeCollection(
        base_ref=resolved_base_ref,
        scope=scope,
        changes=tuple(changes),
        metadata_changes=metadata_changes,
        product_changes=product_changes,
        in_scope_changes=in_scope_changes,
        out_of_scope_changes=out_of_scope_changes,
    )


def resolve_base_ref(
    task: Mapping[str, object],
    *,
    cwd: str | Path | None = None,
    base_ref: str | None = None,
) -> str:
    """Resolve the selected Task baseline without collecting any changes.

    Verification uses this before launching Task checks so an invalid baseline
    cannot cause checks to run before a Run can be recorded.
    """
    repository = find_repository_root(cwd)
    return _resolve_task_base_ref(repository, task, base_ref)


def find_repository_root(cwd: str | Path | None = None) -> Path:
    """Return the Git top-level directory for *cwd* or raise a clear error."""
    working_directory = Path.cwd() if cwd is None else Path(cwd)
    try:
        result = subprocess.run(
            ["git", "-C", str(working_directory), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise GitDiffRepositoryError("Git is required to collect changes.") from error

    if result.returncode != 0 or not result.stdout.strip():
        raise GitDiffRepositoryError(
            "Git change collection must run inside an initialized Git repository."
        )
    return Path(_decode_path(result.stdout.strip())).resolve()


def _tracked_changes(
    repository: Path,
    source: str,
    base_ref: str,
) -> list[tuple[_RawDiffEntry, bool]]:
    raw = _git_output(repository, *_diff_arguments("--raw", source, base_ref, raw=True))
    binary_paths = _binary_paths(
        _git_output(repository, *_diff_arguments("--numstat", source, base_ref, raw=False))
    )
    return [
        (entry, _entry_is_binary(entry, binary_paths))
        for entry in _parse_raw_diff(raw)
    ]


def _diff_arguments(
    format_option: str,
    source: str,
    base_ref: str,
    *,
    raw: bool,
) -> tuple[str, ...]:
    arguments = [
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        format_option,
        "-z",
        "--find-renames",
    ]
    if raw:
        arguments.append("--no-abbrev")

    if source == "committed":
        arguments.extend((base_ref, "HEAD"))
    elif source == "staged":
        arguments.append("--cached")
    elif source != "unstaged":
        raise AssertionError(f"Unsupported tracked change source: {source}")

    arguments.append("--")
    return tuple(arguments)


def _parse_raw_diff(output: bytes) -> list[_RawDiffEntry]:
    entries: list[_RawDiffEntry] = []
    fields = output.split(b"\0")
    index = 0
    while index < len(fields):
        header = fields[index]
        index += 1
        if not header:
            continue

        if not header.startswith(b":"):
            raise GitDiffError("Could not parse Git raw diff output.")
        parts = header[1:].split()
        if len(parts) != 5:
            raise GitDiffError("Could not parse Git raw diff metadata.")

        if index >= len(fields) or not fields[index]:
            raise GitDiffError("Git raw diff record is missing a path.")
        first_path = _decode_path(fields[index])
        index += 1

        git_status = _decode_ascii(parts[4], "Git raw diff status")
        status_code = git_status[:1]
        if status_code in {"R", "C"}:
            if index >= len(fields) or not fields[index]:
                raise GitDiffError("Git rename or copy record is missing its destination path.")
            old_path = first_path
            new_path = _decode_path(fields[index])
            index += 1
        elif status_code == "A":
            old_path = None
            new_path = first_path
        elif status_code == "D":
            old_path = first_path
            new_path = None
        else:
            old_path = first_path
            new_path = first_path

        entries.append(
            _RawDiffEntry(
                git_status=git_status,
                old_path=old_path,
                new_path=new_path,
                old_mode=_mode_or_none(parts[0]),
                new_mode=_mode_or_none(parts[1]),
            )
        )
    return entries


def _binary_paths(output: bytes) -> set[tuple[str, str]]:
    """Return changed path pairs that Git classified as binary in numstat output."""
    binary_paths: set[tuple[str, str]] = set()
    fields = output.split(b"\0")
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        if not record:
            continue

        parts = record.split(b"\t", 2)
        if len(parts) != 3:
            raise GitDiffError("Could not parse Git numstat output.")
        additions, deletions, path_field = parts
        is_binary = additions == b"-" or deletions == b"-"

        if path_field:
            old_path = _decode_path(path_field)
            new_path = old_path
        else:
            if index + 1 >= len(fields) or not fields[index] or not fields[index + 1]:
                raise GitDiffError("Git numstat rename or copy record is missing a path.")
            old_path = _decode_path(fields[index])
            new_path = _decode_path(fields[index + 1])
            index += 2

        if is_binary:
            binary_paths.add((old_path, new_path))
    return binary_paths


def _entry_is_binary(entry: _RawDiffEntry, binary_paths: set[tuple[str, str]]) -> bool:
    old_path = entry.old_path or entry.new_path
    new_path = entry.new_path or entry.old_path
    return old_path is not None and new_path is not None and (old_path, new_path) in binary_paths


def _to_file_change(
    entry: _RawDiffEntry,
    source: str,
    is_binary: bool,
    scope: tuple[str, ...],
) -> FileChange:
    path = entry.new_path or entry.old_path
    if path is None:
        raise GitDiffError("Git diff record is missing both old and new paths.")

    previous_path = entry.old_path if entry.old_path != entry.new_path else None
    paths = tuple(path for path in (entry.old_path, entry.new_path) if path is not None)
    return FileChange(
        source=source,
        status=_status_name(entry.git_status),
        path=path,
        previous_path=previous_path,
        old_mode=entry.old_mode,
        new_mode=entry.new_mode,
        mode_changed=(
            entry.old_mode is not None
            and entry.new_mode is not None
            and entry.old_mode != entry.new_mode
        ),
        is_binary=is_binary,
        in_scope=_paths_match_scope(paths, scope),
    )


def _untracked_paths(repository: Path) -> list[str]:
    output = _git_output(repository, "ls-files", "--others", "--exclude-standard", "-z")
    return [_decode_path(path) for path in output.split(b"\0") if path]


def _is_untracked_binary(repository: Path, path: str) -> bool:
    """Ask Git for a metadata-only numstat comparison against an empty file."""
    result = _git_result(
        repository,
        "diff",
        "--no-index",
        "--no-ext-diff",
        "--no-textconv",
        "--numstat",
        "-z",
        "--",
        "/dev/null",
        path,
    )
    if result.returncode not in {0, 1}:
        _raise_git_failure(result)

    parts = result.stdout.split(b"\t", 2)
    return len(parts) >= 2 and (parts[0] == b"-" or parts[1] == b"-")


def _is_metadata_change(change: FileChange) -> bool:
    paths = [change.path]
    if change.previous_path is not None:
        paths.append(change.previous_path)
    return all(is_harness_metadata_path(path) for path in paths)


def is_harness_metadata_path(path: str) -> bool:
    """Return whether *path* is a Harness metadata path, using path boundaries."""
    normalized = _normalize_relative_path(path, "Git path")
    if normalized in HARNESS_METADATA_FILES:
        return True
    return any(_path_is_within(normalized, directory) for directory in HARNESS_METADATA_DIRECTORIES)


def _paths_match_scope(paths: tuple[str, ...], scope: tuple[str, ...]) -> bool:
    return any(_path_matches_any_scope(path, scope) for path in paths)


def _path_matches_any_scope(path: str, scope: tuple[str, ...]) -> bool:
    normalized_path = _normalize_relative_path(path, "Git path")
    return any(_path_is_within(normalized_path, boundary) for boundary in scope)


def _path_is_within(path: str, boundary: str) -> bool:
    """Compare POSIX path components, never string prefixes."""
    if boundary == ".":
        return True
    path_parts = path.split("/")
    boundary_parts = boundary.split("/")
    return len(path_parts) >= len(boundary_parts) and path_parts[: len(boundary_parts)] == boundary_parts


def _task_baseline(task: Mapping[str, object]) -> str:
    baseline = task.get("baseline")
    if not isinstance(baseline, str) or not baseline:
        raise GitDiffTaskError("Task baseline must be a non-empty Git revision string.")
    return baseline


def _resolve_task_base_ref(
    repository: Path,
    task: Mapping[str, object],
    base_ref: str | None,
) -> str:
    selected_ref = base_ref if base_ref is not None else _task_baseline(task)
    return _resolve_commit(repository, selected_ref)


def _task_scope(task: Mapping[str, object]) -> tuple[str, ...]:
    raw_scope = task.get("scope")
    if not isinstance(raw_scope, list) or not raw_scope:
        raise GitDiffTaskError("Task scope must be a non-empty list of repository-relative paths.")
    return tuple(_normalize_relative_path(path, f"Task scope[{index}]") for index, path in enumerate(raw_scope))


def _normalize_relative_path(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise GitDiffTaskError(f"{context} must be a non-empty repository-relative path.")
    portable_path = value.replace("\\", "/")
    if portable_path.startswith("/") or (len(portable_path) >= 2 and portable_path[1] == ":"):
        raise GitDiffTaskError(f"{context} must be repository-relative.")

    parts = portable_path.split("/")
    if ".." in parts:
        raise GitDiffTaskError(f"{context} must not contain '..' traversal.")
    normalized_parts = [part for part in parts if part not in {"", "."}]
    return "." if not normalized_parts else "/".join(normalized_parts)


def _resolve_commit(repository: Path, reference: str) -> str:
    result = _git_result(
        repository,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{reference}^{{commit}}",
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise GitDiffReferenceError(
            f"Git change collection base ref '{reference}' does not resolve to a commit."
        )
    return _decode_ascii(result.stdout.strip(), "Git commit reference")


def _status_name(git_status: str) -> str:
    return {
        "A": "added",
        "C": "copied",
        "D": "deleted",
        "M": "modified",
        "R": "renamed",
        "T": "type_changed",
        "U": "unmerged",
    }.get(git_status[:1], "unknown")


def _mode_or_none(value: bytes) -> str | None:
    mode = _decode_ascii(value, "Git file mode")
    return None if mode == "000000" else mode


def _git_output(repository: Path, *arguments: str) -> bytes:
    result = _git_result(repository, *arguments)
    if result.returncode != 0:
        _raise_git_failure(result)
    return result.stdout


def _git_result(repository: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise GitDiffError("Git is required to collect changes.") from error


def _raise_git_failure(result: subprocess.CompletedProcess[bytes]) -> None:
    detail = result.stderr.decode("utf-8", "replace").strip()
    message = detail or f"git exited with status {result.returncode}."
    raise GitDiffError(f"Git change collection failed: {message}")


def _decode_path(value: bytes) -> str:
    return value.decode("utf-8", "surrogateescape")


def _decode_ascii(value: bytes, context: str) -> str:
    try:
        return value.decode("ascii")
    except UnicodeDecodeError as error:
        raise GitDiffError(f"Could not decode {context}.") from error
