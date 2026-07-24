"""Small persisted-Evidence fixture transformations shared by tests."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from harness.run_manifest import create_run_manifest


def rewrite_failed_check_as_timeout(
    evidence_path: Path,
    *,
    task_id: str,
    run_id: str,
    check_index: int = 0,
) -> None:
    """Turn one quick failed check into an internally valid timeout fixture.

    Real timeout and process-tree behavior remains covered by checks integration
    tests.  Downstream validators and policies only need a valid persisted Run.
    """
    checks_path = evidence_path / "checks.json"
    checks = json.loads(checks_path.read_text(encoding="utf-8"))
    record = checks["checks"][check_index]
    if record["passed"] or record["exit_code"] in {None, 0}:
        raise AssertionError("Timeout fixture requires an already-failed check.")
    record["timed_out"] = True
    checks_path.write_text(
        json.dumps(checks, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    verification = json.loads(
        (evidence_path / "verification.json").read_text(encoding="utf-8")
    )
    create_run_manifest(
        evidence_path,
        task_id=task_id,
        run_id=run_id,
        evidence_files=tuple(
            PurePosixPath(path)
            for path in verification["evidence_files"]
        ),
    )
