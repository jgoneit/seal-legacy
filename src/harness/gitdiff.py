"""In-memory Git change collection and Task Scope classification.

This module deliberately collects only change metadata.  It does not execute
Task checks, write evidence, expose a CLI command, or retain file contents.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ._path_policy import (
    HARNESS_METADATA_DIRECTORIES,
    HARNESS_METADATA_FILES,
    is_harness_metadata_path as _is_harness_metadata_path,
    path_is_within as _path_is_within,
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

    baseline: str
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
    old_oid: str | None
    new_oid: str | None


@dataclass(frozen=True)
class _FinalTreeCandidate:
    """One path that may differ between a baseline and the final working tree."""

    path: str
    baseline_mode: str | None
    baseline_oid: str | None
    current_present: bool
    current_mode: str | None


@dataclass(frozen=True)
class _FinalTreeCandidateSet:
    """Resolved repository context and final-tree candidates for source readers."""

    repository: Path
    baseline: str
    candidates: tuple[_FinalTreeCandidate, ...]
    tracked_paths: tuple[str, ...]
    gitlink_paths: tuple[str, ...]


@dataclass(frozen=True)
class _BaselineTreeEntry:
    path: str
    mode: str
    object_id: str


@dataclass(frozen=True)
class _FinalTreeContext:
    """Immutable repository and baseline data shared by bounded observations."""

    repository: Path
    baseline: str
    baseline_entries: tuple[_BaselineTreeEntry, ...]


@dataclass(frozen=True)
class _IndexState:
    tracked_modes: tuple[tuple[str, str], ...]
    gitlink_paths: frozenset[str]
    unmerged_paths: frozenset[str]


def collect_changes(
    task: Mapping[str, object],
    *,
    cwd: str | Path | None = None,
) -> ChangeCollection:
    """Collect changes from the saved Task baseline in memory.

    The Task mapping must contain ``baseline`` and ``scope`` fields from a
    normalized Task snapshot.

    The result preserves separate committed, staged, unstaged, and untracked
    layers.  It never runs Task checks or writes files.
    """
    repository = find_repository_root(cwd)
    scope = _task_scope(task)
    baseline = _resolve_task_baseline(repository, task)

    changes: list[FileChange] = []
    for source in ("committed", "staged", "unstaged"):
        for entry, is_binary in _tracked_changes(repository, source, baseline):
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
        baseline=baseline,
        scope=scope,
        changes=tuple(changes),
        metadata_changes=metadata_changes,
        product_changes=product_changes,
        in_scope_changes=in_scope_changes,
        out_of_scope_changes=out_of_scope_changes,
    )


def _collect_final_tree_candidates(
    task: Mapping[str, object],
    *,
    cwd: str | Path | None = None,
    context: _FinalTreeContext | None = None,
) -> _FinalTreeCandidateSet:
    """Collect candidate paths for a baseline-relative final working tree.

    Unlike :func:`collect_changes`, this private boundary deliberately collapses
    committed, staged, and unstaged layers.  The raw comparison is augmented
    with the complete baseline tree and current index inventory so Git hints
    cannot hide a path from a source reader.  The caller still reads actual
    Working Tree nodes and uses the index only to distinguish tracked paths from
    ignored untracked paths.
    """
    resolved = context or _resolve_final_tree_context(task, cwd=cwd)
    repository = resolved.repository
    baseline = resolved.baseline
    output = _git_output(
        repository,
        "diff",
        "--raw",
        "-z",
        "--no-abbrev",
        "--no-renames",
        "--no-ext-diff",
        "--no-textconv",
        baseline,
        "--",
    )

    raw_paths: set[str] = set()
    for entry in _parse_raw_diff(output):
        if entry.git_status[:1] not in {"A", "D", "M", "T"}:
            raise GitDiffError(
                f"Unsupported final-tree Git status '{entry.git_status}'."
            )
        path = entry.new_path or entry.old_path
        if path is None:
            raise GitDiffError("Git final-tree diff record is missing a path.")
        if path in raw_paths:
            raise GitDiffError(
                f"Git final-tree diff contains duplicate path '{path}'."
            )
        raw_paths.add(path)

    baseline_entries = {
        entry.path: entry
        for entry in resolved.baseline_entries
    }
    untracked_paths = frozenset(_untracked_paths(repository))
    index_state = _index_state(repository)
    if index_state.unmerged_paths:
        path = min(index_state.unmerged_paths, key=_path_sort_key)
        raise GitDiffError(
            f"Unsupported final-tree Git status 'U' for '{path}'."
        )
    tracked_modes = dict(index_state.tracked_modes)
    all_paths = (
        set(baseline_entries)
        | set(tracked_modes)
        | set(untracked_paths)
        | raw_paths
    )
    ordered = tuple(
        _FinalTreeCandidate(
            path=path,
            baseline_mode=(
                baseline_entries[path].mode
                if path in baseline_entries
                else None
            ),
            baseline_oid=(
                baseline_entries[path].object_id
                if path in baseline_entries
                else None
            ),
            current_present=(
                path in tracked_modes
                or path in untracked_paths
            ),
            current_mode=tracked_modes.get(path),
        )
        for path in sorted(all_paths, key=_path_sort_key)
    )
    baseline_gitlinks = {
        path
        for path, entry in baseline_entries.items()
        if entry.mode == "160000"
    }
    return _FinalTreeCandidateSet(
        repository=repository,
        baseline=baseline,
        candidates=ordered,
        tracked_paths=tuple(
            sorted(tracked_modes, key=_path_sort_key)
        ),
        gitlink_paths=tuple(
            sorted(
                baseline_gitlinks | set(index_state.gitlink_paths),
                key=_path_sort_key,
            )
        ),
    )


def _resolve_final_tree_context(
    task: Mapping[str, object],
    *,
    cwd: str | Path | None = None,
) -> _FinalTreeContext:
    """Resolve immutable baseline data once for repeated Working Tree reads."""
    repository = find_repository_root(cwd)
    baseline = _resolve_task_baseline(repository, task)
    return _FinalTreeContext(
        repository=repository,
        baseline=baseline,
        baseline_entries=_baseline_tree_entries(repository, baseline),
    )


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
    baseline: str,
) -> list[tuple[_RawDiffEntry, bool]]:
    raw = _git_output(repository, *_diff_arguments("--raw", source, baseline, raw=True))
    binary_paths = _binary_paths(
        _git_output(repository, *_diff_arguments("--numstat", source, baseline, raw=False))
    )
    return [
        (entry, _entry_is_binary(entry, binary_paths))
        for entry in _parse_raw_diff(raw)
    ]


def _diff_arguments(
    format_option: str,
    source: str,
    baseline: str,
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
        arguments.extend((baseline, "HEAD"))
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
                old_oid=_oid_or_none(parts[2]),
                new_oid=_oid_or_none(parts[3]),
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


def _baseline_tree_entries(
    repository: Path,
    baseline: str,
) -> tuple[_BaselineTreeEntry, ...]:
    output = _git_output(
        repository,
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        baseline,
    )
    entries: dict[str, _BaselineTreeEntry] = {}
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            header, raw_path = record.split(b"\t", 1)
        except ValueError as error:
            raise GitDiffError("Could not parse Git baseline-tree metadata.") from error
        parts = header.split()
        if len(parts) != 3:
            raise GitDiffError("Could not parse Git baseline-tree metadata.")
        mode = _decode_ascii(parts[0], "Git baseline-tree mode")
        object_type = _decode_ascii(parts[1], "Git baseline-tree object type")
        object_id = _decode_ascii(parts[2], "Git baseline-tree object id")
        path = _decode_path(raw_path)
        if path in entries:
            raise GitDiffError(
                f"Git baseline tree contains duplicate path '{path}'."
            )
        if object_type not in {"blob", "commit"}:
            raise GitDiffError(
                f"Unsupported Git baseline-tree object type '{object_type}'."
            )
        entries[path] = _BaselineTreeEntry(
            path=path,
            mode=mode,
            object_id=object_id,
        )
    return tuple(
        entries[path]
        for path in sorted(entries, key=_path_sort_key)
    )


def _index_state(repository: Path) -> _IndexState:
    output = _git_output(repository, "ls-files", "--stage", "-z")
    tracked_modes: dict[str, str] = {}
    gitlink_paths: set[str] = set()
    unmerged_paths: set[str] = set()
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            header, raw_path = record.split(b"\t", 1)
        except ValueError as error:
            raise GitDiffError("Could not parse Git staged-file metadata.") from error
        parts = header.split()
        if len(parts) != 3:
            raise GitDiffError("Could not parse Git staged-file metadata.")
        path = _decode_path(raw_path)
        if parts[2] != b"0":
            unmerged_paths.add(path)
            continue
        mode = _decode_ascii(parts[0], "Git staged-file mode")
        if path in tracked_modes:
            raise GitDiffError(
                f"Git staged-file metadata contains duplicate path '{path}'."
            )
        tracked_modes[path] = mode
        if mode == "160000":
            gitlink_paths.add(path)
    return _IndexState(
        tracked_modes=tuple(
            (path, tracked_modes[path])
            for path in sorted(tracked_modes, key=_path_sort_key)
        ),
        gitlink_paths=frozenset(gitlink_paths),
        unmerged_paths=frozenset(unmerged_paths),
    )


def _is_git_ignored(repository: Path, path: str) -> bool:
    """Return Git's current ignore decision for one repository-relative path."""
    result = _git_result(
        repository,
        "check-ignore",
        "--quiet",
        "--",
        path,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    _raise_git_failure(result)
    raise AssertionError("unreachable")


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
    return _is_harness_metadata_path(normalized)


def _paths_match_scope(paths: tuple[str, ...], scope: tuple[str, ...]) -> bool:
    return any(_path_matches_any_scope(path, scope) for path in paths)


def _path_matches_any_scope(path: str, scope: tuple[str, ...]) -> bool:
    normalized_path = _normalize_relative_path(path, "Git path")
    return any(_path_is_within(normalized_path, boundary) for boundary in scope)


def _task_baseline(task: Mapping[str, object]) -> str:
    baseline = task.get("baseline")
    if not isinstance(baseline, str) or not baseline:
        raise GitDiffTaskError("Task baseline must be a non-empty Git revision string.")
    return baseline


def _resolve_task_baseline(
    repository: Path,
    task: Mapping[str, object],
) -> str:
    return _resolve_commit(repository, _task_baseline(task))


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
            f"Task baseline '{reference}' does not resolve to a commit."
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


def _oid_or_none(value: bytes) -> str | None:
    oid = _decode_ascii(value, "Git object id")
    return None if oid and set(oid) == {"0"} else oid


def _path_sort_key(path: str) -> bytes:
    return path.encode("utf-8", "surrogateescape")


def _git_output(repository: Path, *arguments: str) -> bytes:
    result = _git_result(repository, *arguments)
    if result.returncode != 0:
        _raise_git_failure(result)
    return result.stdout


def _git_result(repository: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "-C",
                str(repository),
                *arguments,
            ],
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
