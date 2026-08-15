#!/usr/bin/env python3
"""Exercise the installed Core CLI lifecycle in a disposable repository.

The recorded Verdict is an explicit same-context contract fixture with
``fresh_context=false``. It verifies persistence and completion plumbing only;
it is not an independent review of product changes.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


TASK_ID = "TASK-CLEAN-INSTALL-E2E"


class InstalledCliSmokeError(RuntimeError):
    """Raised when the installed CLI lifecycle violates its contract."""


def main(argv: Sequence[str] | None = None) -> int:
    """Run the lifecycle smoke and return a process exit code."""
    parser = argparse.ArgumentParser(
        description="Smoke-test an installed Core CLI.",
    )
    parser.add_argument(
        "cli",
        help="path to the installed Core executable",
    )
    arguments = parser.parse_args(argv)

    try:
        cli = Path(arguments.cli).resolve(strict=True)
        summary = _exercise_lifecycle(cli)
    except (InstalledCliSmokeError, OSError, ValueError) as error:
        print(f"installed CLI lifecycle smoke failed: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _exercise_lifecycle(cli: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="installed-cli-") as temporary:
        root = Path(temporary)
        repository = root / "repository"
        repository.mkdir()

        _run(("git", "init", "--quiet"), cwd=repository)
        check_definition = {
            "name": "installed-cli-smoke",
            "argv": [
                sys.executable,
                "-c",
                "print('installed CLI lifecycle check')",
            ],
            "required": True,
            "timeout_seconds": 60,
        }
        _write_json(
            repository / ".seal" / "checks.json",
            {
                "schema_version": 1,
                "checks": [check_definition],
            },
        )
        source_path = repository / "src" / "example.txt"
        source_path.parent.mkdir(parents=True)
        source_path.write_text("before\n", encoding="utf-8")
        _run(("git", "add", "."), cwd=repository)
        _run(
            (
                "git",
                "-c",
                "user.name=Installed Core CLI Smoke",
                "-c",
                "user.email=core-cli-smoke@example.invalid",
                "commit",
                "--quiet",
                "-m",
                "fixture",
            ),
            cwd=repository,
        )
        baseline = _run(("git", "rev-parse", "HEAD"), cwd=repository).stdout.strip()

        task_file = root / "task.json"
        _write_json(
            task_file,
            {
                "schema_version": 1,
                "id": TASK_ID,
                "type": "test",
                "objective": "Exercise the installed Core CLI lifecycle.",
                "scope": ["src"],
                "checks": ["installed-cli-smoke"],
                "risk": "low",
                "verifier": {"required": False},
            },
        )
        task = _run_json(
            (str(cli), "task", "create", "--file", str(task_file)),
            cwd=repository,
        )
        _require_exact_keys(
            task,
            {
                "baseline",
                "checks",
                "id",
                "objective",
                "risk",
                "schema_version",
                "scope",
                "type",
                "verifier",
            },
            "task create stdout",
        )
        _require(task.get("id") == TASK_ID, "task create returned the wrong Task id")
        _require(
            task.get("baseline") == baseline,
            "task create returned the wrong Git baseline",
        )
        _require(
            task.get("checks") == [check_definition],
            "task create did not materialize the catalog check",
        )
        _require(
            task.get("verifier") == {"required": False},
            "task create changed the optional verifier fixture",
        )

        source_path.write_text("after\n", encoding="utf-8")
        verification_result = _run_json(
            (str(cli), "verify", TASK_ID),
            cwd=repository,
        )
        _require_exact_keys(
            verification_result,
            {"evidence_path", "run_id"},
            "verify stdout",
        )
        run_id = _required_string(verification_result, "run_id", "verify stdout")
        evidence_path = Path(
            _required_string(
                verification_result,
                "evidence_path",
                "verify stdout",
            )
        )
        _require(evidence_path.is_dir(), "verify did not create its Evidence directory")
        state_bytes_before_run_show = _directory_file_bytes(
            repository / ".seal"
        )
        run_summary = _run_json(
            (str(cli), "run", "show", TASK_ID, "--run-id", run_id),
            cwd=repository,
        )
        _require_exact_keys(
            run_summary,
            {
                "checks",
                "evidence_sha256",
                "mechanical_result",
                "required_checks_pass",
                "run_id",
                "schema_version",
                "scope_pass",
                "scope_violations",
                "source_stable_during_checks",
                "task_id",
            },
            "run show stdout",
        )
        _require(
            run_summary.get("schema_version") == 1
            and run_summary.get("task_id") == TASK_ID
            and run_summary.get("run_id") == run_id,
            "run show returned the wrong schema or Task/run identity",
        )
        _require(
            run_summary.get("mechanical_result") == "pass"
            and run_summary.get("scope_pass") is True
            and run_summary.get("scope_violations") == []
            and run_summary.get("required_checks_pass") is True
            and run_summary.get("source_stable_during_checks") is True,
            "run show did not return the expected passing stored state",
        )
        _require(
            isinstance(run_summary.get("evidence_sha256"), str)
            and bool(run_summary["evidence_sha256"]),
            "run show did not return a non-empty Evidence digest",
        )
        run_summary_checks = run_summary.get("checks")
        _require(
            isinstance(run_summary_checks, list) and len(run_summary_checks) == 1,
            "run show did not return exactly one check result",
        )
        run_summary_check = run_summary_checks[0]
        _require(
            isinstance(run_summary_check, Mapping),
            "run show check result is not an object",
        )
        _require_exact_keys(
            run_summary_check,
            {"exit_code", "name", "passed", "required", "timed_out"},
            "run show check result",
        )
        _require(
            run_summary_check
            == {
                "exit_code": 0,
                "name": "installed-cli-smoke",
                "passed": True,
                "required": True,
                "timed_out": False,
            },
            "run show returned an unexpected check result",
        )
        _require(
            _directory_file_bytes(repository / ".seal")
            == state_bytes_before_run_show,
            "run show changed persisted .seal artifacts",
        )
        verification = _read_json_object(
            evidence_path / "verification.json",
            "verification.json",
        )
        _require(
            verification.get("scope_pass") is True,
            "installed lifecycle fixture did not pass Scope validation",
        )
        _require(
            verification.get("required_checks_pass") is True,
            "installed lifecycle fixture did not pass required checks",
        )
        _require(
            verification.get("mechanical_result") == "pass",
            "installed lifecycle fixture did not record a mechanical pass",
        )
        checks = _read_json_object(evidence_path / "checks.json", "checks.json")
        check_records = checks.get("checks")
        _require(
            isinstance(check_records, list) and len(check_records) == 1,
            "checks.json did not contain the expected check record",
        )
        check_record = check_records[0]
        _require(
            isinstance(check_record, Mapping)
            and check_record.get("exit_code") == 0
            and check_record.get("timed_out") is False
            and check_record.get("passed") is True,
            "installed lifecycle check record was not a successful result",
        )

        bundle_path = root / "bundle"
        bundle_result = _run_json(
            (
                str(cli),
                "verifier",
                "bundle",
                TASK_ID,
                "--run-id",
                run_id,
                "--output",
                str(bundle_path),
            ),
            cwd=repository,
        )
        _require_exact_keys(
            bundle_result,
            {
                "bundle_path",
                "bundle_sha256",
                "manifest_path",
                "run_id",
                "task_id",
                "total_size_bytes",
            },
            "verifier bundle stdout",
        )
        _require(
            bundle_result.get("task_id") == TASK_ID
            and bundle_result.get("run_id") == run_id,
            "verifier bundle returned the wrong Task/run identity",
        )
        _require(
            Path(
                _required_string(bundle_result, "bundle_path", "bundle stdout")
            ).resolve()
            == bundle_path.resolve()
            and Path(
                _required_string(bundle_result, "manifest_path", "bundle stdout")
            ).resolve()
            == (bundle_path / "manifest.json").resolve(),
            "verifier bundle returned unexpected output paths",
        )
        bundle_manifest = _read_json_object(
            bundle_path / "manifest.json",
            "bundle manifest",
        )
        _require(
            bundle_manifest.get("task_id") == TASK_ID
            and bundle_manifest.get("run_id") == run_id,
            "bundle manifest contains the wrong Task/run identity",
        )
        bundle_files = bundle_manifest.get("files")
        _require(
            isinstance(bundle_files, list)
            and "verifier.md"
            in {
                record.get("path")
                for record in bundle_files
                if isinstance(record, Mapping)
            },
            "bundle manifest does not include packaged verifier instructions",
        )
        _require(
            isinstance(bundle_manifest.get("source_evidence_sha256"), str)
            and isinstance(bundle_manifest.get("bundle_sha256"), str),
            "bundle manifest is missing its Evidence or bundle digest",
        )
        _require(
            run_summary.get("evidence_sha256")
            == bundle_manifest.get("source_evidence_sha256"),
            "run show and bundle disagree on the validated Evidence digest",
        )
        _require(
            bundle_result.get("bundle_sha256")
            == bundle_manifest.get("bundle_sha256")
            and bundle_result.get("total_size_bytes")
            == bundle_manifest.get("total_size_bytes"),
            "verifier bundle stdout does not match its manifest",
        )

        verdict_file = root / "verdict.json"
        verdict = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": run_id,
            "verifier": {
                "kind": "manual",
                "runner": "installed-cli-contract-fixture",
                "model": None,
                "fresh_context": False,
            },
            "verdict": "pass",
            "summary": (
                "Synthetic installed-CLI contract fixture; "
                "not an independent verification."
            ),
            "findings": [],
            "reviewed_at": "2026-07-23T00:00:00Z",
        }
        _write_json(verdict_file, verdict)
        record_result = _run_json(
            (
                str(cli),
                "verifier",
                "record",
                TASK_ID,
                "--run-id",
                run_id,
                "--file",
                str(verdict_file),
            ),
            cwd=repository,
        )
        _require_exact_keys(
            record_result,
            {"raw_verdict_path", "run_id", "task_id", "verdict_path"},
            "verifier record stdout",
        )
        _require(
            record_result.get("task_id") == TASK_ID
            and record_result.get("run_id") == run_id,
            "verifier record returned the wrong Task/run identity",
        )
        _require(
            Path(
                _required_string(record_result, "raw_verdict_path", "record stdout")
            ).is_file()
            and Path(
                _required_string(record_result, "verdict_path", "record stdout")
            ).is_file(),
            "verifier record did not persist both Verdict files",
        )

        shown_verdict = _run_json(
            (
                str(cli),
                "verifier",
                "show",
                TASK_ID,
                "--run-id",
                run_id,
            ),
            cwd=repository,
        )
        _require(
            shown_verdict == verdict,
            "verifier show did not return the recorded canonical Verdict",
        )

        completion_result = _run_json(
            (str(cli), "complete", TASK_ID, "--run-id", run_id),
            cwd=repository,
        )
        _require_exact_keys(
            completion_result,
            {"completion_path", "run_id", "task_id"},
            "complete stdout",
        )
        _require(
            completion_result.get("task_id") == TASK_ID
            and completion_result.get("run_id") == run_id,
            "complete returned the wrong Task/run identity",
        )
        completion_path = Path(
            _required_string(
                completion_result,
                "completion_path",
                "complete stdout",
            )
        )
        completion = _read_json_object(completion_path, "completion.json")
        expected_completion = {
            "task_id": TASK_ID,
            "run_id": run_id,
            "mechanical_result": "pass",
            "verifier_required": False,
            "verifier_runner": "installed-cli-contract-fixture",
            "verifier_verdict": "pass",
            "blocker_count": 0,
            "warning_count": 0,
            "note_count": 0,
            "final_result": "pass",
        }
        for field, expected in expected_completion.items():
            _require(
                completion.get(field) == expected,
                f"completion.json has an unexpected {field}",
            )
        _require(
            completion.get("evidence_sha256")
            == bundle_manifest.get("source_evidence_sha256"),
            "completion.json does not reference the bundled Evidence digest",
        )

        return {
            "task_id": TASK_ID,
            "run_id": run_id,
            "lifecycle": [
                "task create",
                "verify",
                "run show",
                "verifier bundle",
                "verifier record",
                "verifier show",
                "complete",
            ],
            "verdict_fixture_fresh_context": False,
        }


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise InstalledCliSmokeError(
            f"could not execute {shlex.join(command)}: {error}"
        ) from error
    if result.returncode != 0:
        raise InstalledCliSmokeError(
            f"{shlex.join(command)} exited {result.returncode}; "
            f"stdout={result.stdout!r}; stderr={result.stderr!r}"
        )
    if result.stderr:
        raise InstalledCliSmokeError(
            f"{shlex.join(command)} wrote unexpected stderr: {result.stderr!r}"
        )
    return result


def _run_json(command: Sequence[str], *, cwd: Path) -> dict[str, Any]:
    result = _run(command, cwd=cwd)
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise InstalledCliSmokeError(
            f"{shlex.join(command)} did not write valid stdout JSON"
        ) from error
    if not isinstance(value, dict):
        raise InstalledCliSmokeError(
            f"{shlex.join(command)} stdout JSON must be an object"
        )
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json_object(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InstalledCliSmokeError(f"{description} is missing or invalid") from error
    if not isinstance(value, dict):
        raise InstalledCliSmokeError(f"{description} must be a JSON object")
    return value


def _directory_file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _required_string(
    value: Mapping[str, Any],
    field: str,
    description: str,
) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise InstalledCliSmokeError(
            f"{description} field {field} must be a non-empty string"
        )
    return result


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    description: str,
) -> None:
    if set(value) != expected:
        raise InstalledCliSmokeError(
            f"{description} fields were {sorted(value)}; expected {sorted(expected)}"
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InstalledCliSmokeError(message)


if __name__ == "__main__":
    raise SystemExit(main())
