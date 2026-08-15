#!/usr/bin/env python3
"""Synchronize canonical Verdict contracts into package resources."""

from __future__ import annotations

import argparse
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_MIRRORS = (
    (
        PROJECT_ROOT / "schemas" / "verdict.schema.json",
        PROJECT_ROOT / "src" / "seal_legacy" / "resources" / "verdict.schema.json",
    ),
    (
        PROJECT_ROOT / "prompts" / "verifier.md",
        PROJECT_ROOT / "src" / "seal_legacy" / "resources" / "verifier.md",
    ),
)


def main() -> int:
    """Copy canonical contracts, or verify their byte-for-byte parity."""
    parser = argparse.ArgumentParser(
        description="sync canonical Verdict contracts into package resources"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail instead of writing when a packaged resource differs",
    )
    arguments = parser.parse_args()

    mismatches: list[tuple[Path, Path]] = []
    for source, mirror in CONTRACT_MIRRORS:
        try:
            source_bytes = source.read_bytes()
        except OSError as error:
            parser.error(
                f"could not read canonical contract {source.relative_to(PROJECT_ROOT)}: {error}"
            )
        try:
            mirror_bytes = mirror.read_bytes()
        except OSError:
            mirror_bytes = None
        if mirror_bytes != source_bytes:
            mismatches.append((source, mirror))
            if not arguments.check:
                mirror.parent.mkdir(parents=True, exist_ok=True)
                mirror.write_bytes(source_bytes)

    if arguments.check and mismatches:
        for source, mirror in mismatches:
            print(
                "contract mirror differs: "
                f"{mirror.relative_to(PROJECT_ROOT)} != {source.relative_to(PROJECT_ROOT)}"
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
