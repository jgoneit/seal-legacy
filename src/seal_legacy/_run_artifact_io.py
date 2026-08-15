"""Concrete internal I/O primitives for files inside one Evidence Run."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, BinaryIO, TextIO


class RunArtifactPathError(ValueError):
    """Raised when an Evidence artifact path is not a safe relative POSIX path."""


class RunArtifactReadError(OSError):
    """Raised when a confined Evidence artifact cannot be read."""

    def __init__(self, reason: str, relative_path: PurePosixPath) -> None:
        super().__init__(reason, relative_path.as_posix())
        self.reason = reason
        self.relative_path = relative_path


def safe_run_relative_path(value: object, context: str) -> PurePosixPath:
    """Return one canonical relative POSIX path that cannot leave a Run."""
    if not isinstance(value, str) or not value:
        raise RunArtifactPathError(
            f"{context} must be a non-empty relative POSIX path."
        )
    if "\\" in value or "\x00" in value:
        raise RunArtifactPathError(f"{context} must use a relative POSIX path.")
    path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    parts = value.split("/")
    if (
        path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or not path.parts
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise RunArtifactPathError(f"{context} must stay inside the Run directory.")
    return path


def read_run_artifact_bytes(
    directory: Path,
    relative_path: PurePosixPath,
) -> bytes:
    """Read raw bytes only when the resolved regular file stays in *directory*."""
    try:
        resolved_directory = directory.resolve(strict=True)
        candidate = resolved_directory.joinpath(*relative_path.parts)
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise RunArtifactReadError("missing", relative_path) from error
    if (
        not resolved_directory.is_dir()
        or not resolved.is_relative_to(resolved_directory)
        or not resolved.is_file()
    ):
        raise RunArtifactReadError("unsafe", relative_path)
    try:
        return resolved.read_bytes()
    except OSError as error:
        raise RunArtifactReadError("unreadable", relative_path) from error


def atomic_write_json(path: str | Path, value: object) -> None:
    """Write JSON through a same-directory temporary file and rename it atomically."""

    def write(output: TextIO) -> None:
        json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")

    atomic_write(Path(path), mode="w", writer=write)


def atomic_write_bytes(path: str | Path, value: bytes) -> None:
    """Atomically write a binary artifact using the same no-partial-file rule."""

    def write(output: BinaryIO) -> None:
        output.write(value)

    atomic_write(Path(path), mode="wb", writer=write)


def atomic_write(
    path: Path,
    *,
    mode: str,
    writer: Callable[[Any], None],
    create_parent: bool = True,
) -> None:
    """Apply the shared same-directory fsync-and-replace write primitive."""
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode=mode,
            encoding="utf-8" if mode == "w" else None,
            errors="backslashreplace" if mode == "w" else None,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            writer(output)
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
