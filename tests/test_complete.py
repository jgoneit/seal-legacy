"""End-to-end coverage for Phase 1c evidence completion and exit codes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from harness.evidence import verify_task
from harness.exit_codes import ExitCode
from harness.task import create_task
from harness.verdict import record_verdict
from tests._evidence_fixtures import rewrite_failed_check_as_timeout


class CompleteCommandTests(unittest.TestCase):
    """Exercise the installed CLI behavior against disposable repositories."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self._git("init", "--quiet")
        self._write(".harness/checks.json", '{"checks": []}\n')
        self._write("src/example.txt", "fixture\n")
        self._git("add", ".")
        self._git(
            "-c",
            "user.name=Harness Test",
            "-c",
            "user.email=harness-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _git(self, *arguments: str) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=self.repository,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def _write(self, relative_path: str, contents: str | bytes) -> None:
        path = self.repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contents, bytes):
            path.write_bytes(contents)
        else:
            path.write_text(contents, encoding="utf-8")

    @staticmethod
    def _python_check(
        name: str,
        program: str,
        *,
        required: bool = True,
        timeout_seconds: int | None = None,
    ) -> dict[str, object]:
        check: dict[str, object] = {
            "name": name,
            "argv": [sys.executable, "-c", program],
            "required": required,
        }
        if timeout_seconds is not None:
            check["timeout_seconds"] = timeout_seconds
        return check

    def _create_task(
        self,
        *,
        task_id: str = "TASK-COMPLETE",
        checks: list[dict[str, object]] | None = None,
        verifier_required: bool = False,
    ) -> None:
        specification = {
            "schema_version": 1,
            "id": task_id,
            "type": "test",
            "objective": "Exercise Phase 1c completion.",
            "scope": ["src"],
            "checks": checks
            if checks is not None
            else [self._python_check("ok", "print('ok')")],
            "risk": "low",
            "verifier": {"required": verifier_required},
        }
        source = self.root / f"{task_id}.json"
        source.write_text(json.dumps(specification), encoding="utf-8")
        create_task(source, cwd=self.repository)

    def _run_cli(
        self, *arguments: str, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(SOURCE_ROOT)
        if existing_pythonpath:
            environment["PYTHONPATH"] += os.pathsep + existing_pythonpath
        return subprocess.run(
            [sys.executable, "-m", "harness", *arguments],
            cwd=cwd if cwd is not None else self.repository,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def _complete(
        self, task_id: str, run_id: str, *, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        return self._run_cli("complete", task_id, "--run-id", run_id, cwd=cwd)

    def _record_verdict(
        self,
        run_id: str,
        *,
        task_id: str = "TASK-COMPLETE",
        verdict: str = "pass",
        findings: list[dict[str, object]] | None = None,
    ) -> None:
        document = {
            "schema_version": 1,
            "task_id": task_id,
            "run_id": run_id,
            "verifier": {
                "kind": "manual",
                "runner": "human",
                "model": None,
                "fresh_context": True,
            },
            "verdict": verdict,
            "summary": "Manual verifier result.",
            "findings": [] if findings is None else findings,
            "reviewed_at": "2026-07-16T00:00:00Z",
        }
        source = self.root / f"{task_id}-{run_id}-verdict.json"
        source.write_text(json.dumps(document), encoding="utf-8")
        record_verdict(task_id, run_id, source, cwd=self.repository)

    @staticmethod
    def _finding(severity: str) -> dict[str, object]:
        return {
            "severity": severity,
            "code": f"{severity.upper()}-001",
            "title": f"{severity} finding",
            "detail": "Verifier finding for completion coverage.",
            "path": "src/example.txt",
            "line": 1,
        }

    def test_exit_code_values_are_stable(self) -> None:
        self.assertEqual(int(ExitCode.SUCCESS), 0)
        self.assertEqual(int(ExitCode.INVALID_INPUT_OR_SCHEMA), 2)
        self.assertEqual(int(ExitCode.GIT_OR_REPOSITORY_ERROR), 3)
        self.assertEqual(int(ExitCode.SCOPE_VIOLATION), 4)
        self.assertEqual(int(ExitCode.REQUIRED_CHECK_FAILURE), 5)
        self.assertEqual(int(ExitCode.TIMEOUT), 6)
        self.assertEqual(int(ExitCode.REQUIRED_VERIFIER_EVIDENCE_MISSING), 7)
        self.assertEqual(int(ExitCode.EVIDENCE_MISSING_OR_CORRUPT), 8)
        self.assertEqual(int(ExitCode.SOURCE_BINDING_NOT_SATISFIED), 9)

    def test_complete_writes_completion_without_rerunning_checks(self) -> None:
        counter_path = self.root / "check-count.txt"
        program = (
            "from pathlib import Path; "
            f"path = Path({str(counter_path)!r}); "
            "path.write_text(path.read_text() + 'x' if path.exists() else 'x')"
        )
        self._create_task(checks=[self._python_check("count", program)])

        run = verify_task("TASK-COMPLETE", cwd=self.repository)
        self.assertEqual(counter_path.read_text(encoding="utf-8"), "x")

        result = self._complete("TASK-COMPLETE", run.run_id)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(counter_path.read_text(encoding="utf-8"), "x")
        response = json.loads(result.stdout)
        completion_path = Path(response["completion_path"])
        self.assertTrue(completion_path.is_file())
        completion = json.loads(completion_path.read_text(encoding="utf-8"))
        self.assertEqual(
            completion,
            {
                "schema_version": 1,
                "task_id": "TASK-COMPLETE",
                "run_id": run.run_id,
                "evidence_sha256": completion["evidence_sha256"],
                "mechanical_result": "pass",
                "verifier_required": False,
                "verifier_runner": None,
                "verifier_verdict": None,
                "blocker_count": 0,
                "warning_count": 0,
                "note_count": 0,
                "final_result": "pass",
                "completed_at": completion["completed_at"],
            },
        )

    def test_task_run_mismatch_returns_invalid_input_exit_code(self) -> None:
        self._create_task(task_id="TASK-FIRST")
        self._create_task(task_id="TASK-SECOND")
        run = verify_task("TASK-FIRST", cwd=self.repository)
        copied_run = self.repository / ".harness" / "evidence" / "TASK-SECOND" / run.run_id
        copied_run.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(run.evidence_path, copied_run)

        result = self._complete("TASK-SECOND", run.run_id)

        self.assertEqual(result.returncode, 2, result.stderr)

    def test_missing_evidence_returns_evidence_exit_code(self) -> None:
        self._create_task()

        result = self._complete("TASK-COMPLETE", "missing-run")

        self.assertEqual(result.returncode, 8, result.stderr)

    def test_corrupt_evidence_returns_evidence_exit_code(self) -> None:
        self._create_task(verifier_required=True)
        run = verify_task("TASK-COMPLETE", cwd=self.repository)
        (run.evidence_path / "verification.json").write_text("{", encoding="utf-8")

        result = self._complete("TASK-COMPLETE", run.run_id)

        self.assertEqual(result.returncode, 8, result.stderr)

    def test_inconsistent_mechanical_result_returns_evidence_exit_code(self) -> None:
        self._create_task()
        run = verify_task("TASK-COMPLETE", cwd=self.repository)
        verification_path = run.evidence_path / "verification.json"
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        verification["mechanical_result"] = "fail"
        verification_path.write_text(json.dumps(verification), encoding="utf-8")

        result = self._complete("TASK-COMPLETE", run.run_id)

        self.assertEqual(result.returncode, 8, result.stderr)

    def test_scope_violation_rejects_completion(self) -> None:
        self._create_task(
            checks=[
                self._python_check(
                    "timeout", "import time; time.sleep(30)", timeout_seconds=1
                )
            ]
        )
        self._write("docs/outside.txt", "outside scope\n")
        run = verify_task("TASK-COMPLETE", cwd=self.repository)

        result = self._complete("TASK-COMPLETE", run.run_id)

        self.assertEqual(result.returncode, 4, result.stderr)

    def test_required_check_failure_rejects_completion(self) -> None:
        self._create_task(
            checks=[self._python_check("fail", "import sys; sys.exit(23)")]
        )
        run = verify_task("TASK-COMPLETE", cwd=self.repository)

        result = self._complete("TASK-COMPLETE", run.run_id)

        self.assertEqual(result.returncode, 5, result.stderr)

    def test_verify_returns_success_after_recording_required_check_failure(self) -> None:
        self._create_task(
            checks=[self._python_check("fail", "import sys; sys.exit(23)")]
        )

        result = self._run_cli("verify", "TASK-COMPLETE")

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        verification_path = Path(response["evidence_path"]) / "verification.json"
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        self.assertFalse(verification["required_checks_pass"])
        self.assertEqual(verification["mechanical_result"], "fail")

    def test_required_check_timeout_rejects_completion(self) -> None:
        self._create_task(
            checks=[
                self._python_check(
                    "timeout", "import sys; sys.exit(24)", timeout_seconds=1
                )
            ]
        )
        run = verify_task("TASK-COMPLETE", cwd=self.repository)
        rewrite_failed_check_as_timeout(
            run.evidence_path,
            task_id="TASK-COMPLETE",
            run_id=run.run_id,
        )

        result = self._complete("TASK-COMPLETE", run.run_id)

        self.assertEqual(result.returncode, 6, result.stderr)

    def test_required_verifier_without_verdict_rejects_completion(self) -> None:
        self._create_task(verifier_required=True)
        self._write("docs/outside.txt", "outside scope\n")
        run = verify_task("TASK-COMPLETE", cwd=self.repository)

        result = self._complete("TASK-COMPLETE", run.run_id)

        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertFalse((run.evidence_path / "completion.json").exists())

    def test_optional_verifier_task_completes_from_mechanical_evidence_only(self) -> None:
        self._create_task(verifier_required=False)
        run = verify_task("TASK-COMPLETE", cwd=self.repository)

        result = self._complete("TASK-COMPLETE", run.run_id)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_required_verifier_pass_verdict_allows_completion(self) -> None:
        self._create_task(verifier_required=True)
        run = verify_task("TASK-COMPLETE", cwd=self.repository)
        self._record_verdict(run.run_id)

        result = self._complete("TASK-COMPLETE", run.run_id)

        self.assertEqual(result.returncode, 0, result.stderr)
        completion = json.loads(Path(json.loads(result.stdout)["completion_path"]).read_text())
        self.assertEqual(completion["verifier_required"], True)
        self.assertEqual(completion["verifier_runner"], "human")
        self.assertEqual(completion["verifier_verdict"], "pass")
        self.assertEqual(completion["blocker_count"], 0)
        self.assertEqual(completion["warning_count"], 0)
        self.assertEqual(completion["note_count"], 0)
        self.assertEqual(completion["final_result"], "pass")

    def test_warning_only_verdict_does_not_block_completion(self) -> None:
        self._create_task(verifier_required=False)
        run = verify_task("TASK-COMPLETE", cwd=self.repository)
        self._record_verdict(
            run.run_id,
            findings=[self._finding("warning")],
        )

        result = self._complete("TASK-COMPLETE", run.run_id)

        self.assertEqual(result.returncode, 0, result.stderr)
        completion = json.loads(Path(json.loads(result.stdout)["completion_path"]).read_text())
        self.assertEqual(completion["warning_count"], 1)
        self.assertEqual(completion["final_result"], "pass")

    def test_optional_verifier_blocker_rejects_completion(self) -> None:
        self._create_task(verifier_required=False)
        run = verify_task("TASK-COMPLETE", cwd=self.repository)
        self._record_verdict(
            run.run_id,
            findings=[self._finding("blocker")],
        )

        result = self._complete("TASK-COMPLETE", run.run_id)

        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertFalse((run.evidence_path / "completion.json").exists())

    def test_fail_and_unable_verdicts_reject_completion(self) -> None:
        self._create_task(verifier_required=False)
        run = verify_task("TASK-COMPLETE", cwd=self.repository)

        for verdict in ("fail", "unable"):
            with self.subTest(verdict=verdict):
                self._record_verdict(run.run_id, verdict=verdict)
                result = self._complete("TASK-COMPLETE", run.run_id)
                self.assertEqual(result.returncode, 7, result.stderr)
                self.assertFalse((run.evidence_path / "completion.json").exists())

    def test_malformed_recorded_verdict_never_completes_as_pass(self) -> None:
        self._create_task(verifier_required=False)
        run = verify_task("TASK-COMPLETE", cwd=self.repository)
        self._record_verdict(run.run_id)
        (run.evidence_path / "verdict.raw.json").write_text("{", encoding="utf-8")

        result = self._complete("TASK-COMPLETE", run.run_id)

        self.assertEqual(result.returncode, 8, result.stderr)
        self.assertFalse((run.evidence_path / "completion.json").exists())

    def test_invalid_run_id_and_missing_run_id_return_invalid_input_exit_code(self) -> None:
        invalid = self._complete("TASK-COMPLETE", "../not-a-run")
        omitted = self._run_cli("complete", "TASK-COMPLETE")

        self.assertEqual(invalid.returncode, 2, invalid.stderr)
        self.assertEqual(omitted.returncode, 2, omitted.stderr)

    def test_complete_rejects_product_source_changes_after_verification(self) -> None:
        self._create_task()
        run = verify_task("TASK-COMPLETE", cwd=self.repository)
        self._write("src/example.txt", "changed after verification\n")

        result = self._complete("TASK-COMPLETE", run.run_id)

        self.assertEqual(result.returncode, 9, result.stderr)
        self.assertFalse((run.evidence_path / "completion.json").exists())

    def test_verify_rejects_removed_base_ref_option(self) -> None:
        self._create_task()
        self._write("docs/hidden.txt", "committed after the Task baseline\n")
        self._git("add", "docs/hidden.txt")
        self._git(
            "-c",
            "user.name=Harness Test",
            "-c",
            "user.email=harness-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "post-baseline product change",
        )

        result = self._run_cli("verify", "TASK-COMPLETE", "--base-ref", "HEAD")

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse(
            (self.repository / ".harness" / "evidence" / "TASK-COMPLETE").exists()
        )

    def test_non_repository_returns_git_repository_exit_code(self) -> None:
        non_repository = self.root / "not-a-repository"
        non_repository.mkdir()

        result = self._complete("TASK-COMPLETE", "some-run", cwd=non_repository)

        self.assertEqual(result.returncode, 3, result.stderr)
