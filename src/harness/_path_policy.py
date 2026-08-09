"""Pure internal Git path policy shared across Core trust domains."""

from __future__ import annotations


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


def git_path_sort_key(path: str) -> bytes:
    """Return Git's byte-oriented ordering key for one decoded path."""
    return path.encode("utf-8", "surrogateescape")


def path_is_within(path: str, boundary: str) -> bool:
    """Compare normalized POSIX path components, never string prefixes."""
    if boundary == ".":
        return True
    path_parts = path.split("/")
    boundary_parts = boundary.split("/")
    return (
        len(path_parts) >= len(boundary_parts)
        and path_parts[: len(boundary_parts)] == boundary_parts
    )


def change_is_within_scope(
    *,
    status: str,
    path: str,
    previous_path: str | None,
    scope: tuple[str, ...],
) -> bool:
    """Classify one normalized change against normalized Scope boundaries."""
    affected_paths = (
        (path, previous_path)
        if status == "renamed" and previous_path is not None
        else (path,)
    )
    return all(
        any(path_is_within(affected_path, boundary) for boundary in scope)
        for affected_path in affected_paths
    )


def is_harness_metadata_path(path: str) -> bool:
    """Classify one normalized repository path as Harness-owned metadata."""
    if path in HARNESS_METADATA_FILES:
        return True
    return any(
        path_is_within(path, directory)
        for directory in HARNESS_METADATA_DIRECTORIES
    )
