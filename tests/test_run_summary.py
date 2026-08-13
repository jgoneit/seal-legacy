"""CLI coverage for the Core-authoritative validated Run Summary view."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from harness import cli
from harness.evidence import verify_task
from harness.run_validator import validate_run
from harness.task import create_task
from tests._evidence_fixtures import rewrite_failed_check_as_timeout


SUMMARY_KEYS = {
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
}
CHECK_KEYS = {"exit_code", "name", "passed", "required", "timed_out"}
SCOPE_VIOLATION_KEYS = {"path", "previous_path", "source", "status"}


@contextlib.contextmanager
def change_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class ValidatedRunSummaryCommandTests(unittest.TestCase):
    """Expose validated stored state without running a lifecycle transition."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self._git("init", "--quiet")
        self._write(".harness/checks.json", '{"checks": []}\n')
        self._write("src/example.txt", "before\n")
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

    def _write(self, relative_path: str, contents: str | bytes) -> Path:
        path = self.repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contents, bytes):
            path.write_bytes(contents)
        else:
            path.write_text(contents, encoding="utf-8")
        return path

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
        task_id: str = "TASK-SUMMARY",
        checks: list[dict[str, object]] | None = None,
        scope: list[str] | None = None,
    ) -> None:
        specification = {
            "schema_version": 1,
            "id": task_id,
            "type": "test",
            "objective": "Exercise the validated Run Summary command.",
            "scope": ["src"] if scope is None else scope,
            "checks": checks
            if checks is not None
            else [self._python_check("passing", "print('ok')")],
            "risk": "low",
            "verifier": {"required": False},
        }
        source = self.root / f"{task_id}.json"
        source.write_text(json.dumps(specification), encoding="utf-8")
        create_task(source, cwd=self.repository)

    def _run_cli(
        self,
        *arguments: str,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(SOURCE_ROOT)
        if existing_pythonpath:
            environment["PYTHONPATH"] += os.pathsep + existing_pythonpath
        return subprocess.run(
            [sys.executable, "-m", "harness", *arguments],
            cwd=self.repository if cwd is None else cwd,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def _run_show(
        self,
        task_id: str,
        run_id: str,
        *,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self._run_cli(
            "run",
            "show",
            task_id,
            "--run-id",
            run_id,
            cwd=cwd,
        )

    def _success_summary(
        self,
        result: subprocess.CompletedProcess[str],
    ) -> dict[str, object]:
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertTrue(result.stdout.endswith("\n"))
        self.assertFalse(result.stdout.endswith("\n\n"))
        summary = json.loads(result.stdout)
        self.assertIsInstance(summary, dict)
        self.assertEqual(set(summary), SUMMARY_KEYS)
        self.assertEqual(summary["schema_version"], 1)
        for record in summary["checks"]:
            self.assertEqual(set(record), CHECK_KEYS)
        for violation in summary["scope_violations"]:
            self.assertEqual(set(violation), SCOPE_VIOLATION_KEYS)
        return summary

    def _artifact_bytes(self) -> dict[str, bytes]:
        harness_root = self.repository / ".harness"
        return {
            path.relative_to(harness_root).as_posix(): path.read_bytes()
            for path in sorted(harness_root.rglob("*"))
            if path.is_file() and not path.is_symlink()
        }

    def test_exact_pass_summary_is_read_only_and_calls_only_validator_once(self) -> None:
        counter = self.root / "check-counter.txt"
        self._create_task(
            checks=[
                self._python_check(
                    "required-pass",
                    "from pathlib import Path; "
                    f"p = Path({str(counter)!r}); "
                    "p.write_text(str(int(p.read_text(encoding='utf-8')) + 1) "
                    "if p.exists() else '1', encoding='utf-8')",
                ),
                self._python_check(
                    "optional-fail",
                    "import sys; sys.exit(7)",
                    required=False,
                ),
            ]
        )
        self._write("src/example.txt", "candidate\n")
        run = verify_task("TASK-SUMMARY", cwd=self.repository)
        validated = validate_run("TASK-SUMMARY", run.run_id, cwd=self.repository)

        # Consumer artifacts are deliberately outside the mechanical Run validator.
        (run.evidence_path / "verdict.raw.json").write_text("{", encoding="utf-8")
        (run.evidence_path / "verdict.json").write_text("{}", encoding="utf-8")
        (run.evidence_path / "completion.json").write_text("{}", encoding="utf-8")
        self._write("src/example.txt", "current source drift after verification\n")
        before = self._artifact_bytes()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            change_directory(self.repository),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
            mock.patch.object(cli, "validate_run", wraps=validate_run) as validator,
            mock.patch.object(cli, "verify_task") as verify,
            mock.patch.object(cli, "complete_task") as complete,
            mock.patch.object(cli, "record_verdict") as record_verdict,
            mock.patch.object(cli, "show_verdict") as show_verdict,
            mock.patch.object(cli, "create_verification_bundle") as bundle,
        ):
            return_code = cli.main(
                ["run", "show", "TASK-SUMMARY", "--run-id", run.run_id]
            )

        self.assertEqual(return_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        validator.assert_called_once_with("TASK-SUMMARY", run.run_id)
        verify.assert_not_called()
        complete.assert_not_called()
        record_verdict.assert_not_called()
        show_verdict.assert_not_called()
        bundle.assert_not_called()
        self.assertEqual(counter.read_text(encoding="utf-8"), "1")
        self.assertEqual(self._artifact_bytes(), before)

        summary = json.loads(stdout.getvalue())
        self.assertEqual(
            summary,
            {
                "checks": [
                    {
                        "exit_code": 0,
                        "name": "required-pass",
                        "passed": True,
                        "required": True,
                        "timed_out": False,
                    },
                    {
                        "exit_code": 7,
                        "name": "optional-fail",
                        "passed": False,
                        "required": False,
                        "timed_out": False,
                    },
                ],
                "evidence_sha256": validated.evidence_sha256,
                "mechanical_result": "pass",
                "required_checks_pass": True,
                "run_id": run.run_id,
                "schema_version": 1,
                "scope_pass": True,
                "scope_violations": [],
                "source_stable_during_checks": True,
                "task_id": "TASK-SUMMARY",
            },
        )
        self.assertTrue(stdout.getvalue().endswith("\n"))
        self.assertFalse(stdout.getvalue().endswith("\n\n"))

    def test_required_failure_and_scope_violation_are_valid_summary_state(self) -> None:
        self._create_task(
            checks=[self._python_check("required-fail", "import sys; sys.exit(23)")]
        )
        self._write("docs/outside.txt", "outside scope\n")
        self._write("other/second.txt", "second outside-scope change\n")
        run = verify_task("TASK-SUMMARY", cwd=self.repository)

        summary = self._success_summary(self._run_show("TASK-SUMMARY", run.run_id))

        self.assertEqual(summary["mechanical_result"], "fail")
        self.assertFalse(summary["required_checks_pass"])
        self.assertFalse(summary["scope_pass"])
        self.assertTrue(summary["source_stable_during_checks"])
        self.assertEqual(
            summary["checks"],
            [
                {
                    "exit_code": 23,
                    "name": "required-fail",
                    "passed": False,
                    "required": True,
                    "timed_out": False,
                }
            ],
        )
        self.assertEqual(
            summary["scope_violations"],
            [
                {
                    "path": "docs/outside.txt",
                    "previous_path": None,
                    "source": "untracked",
                    "status": "untracked",
                },
                {
                    "path": "other/second.txt",
                    "previous_path": None,
                    "source": "untracked",
                    "status": "untracked",
                },
            ],
        )

    def test_timeout_is_valid_summary_state_and_remains_distinct(self) -> None:
        self._create_task(
            checks=[
                self._python_check(
                    "required-timeout",
                    "import sys; sys.exit(24)",
                    timeout_seconds=1,
                )
            ]
        )
        run = verify_task("TASK-SUMMARY", cwd=self.repository)
        rewrite_failed_check_as_timeout(
            run.evidence_path,
            task_id="TASK-SUMMARY",
            run_id=run.run_id,
        )

        summary = self._success_summary(self._run_show("TASK-SUMMARY", run.run_id))

        self.assertEqual(summary["mechanical_result"], "fail")
        self.assertFalse(summary["required_checks_pass"])
        self.assertEqual(
            summary["checks"],
            [
                {
                    "exit_code": 24,
                    "name": "required-timeout",
                    "passed": False,
                    "required": True,
                    "timed_out": True,
                }
            ],
        )

    def test_unstartable_check_exposes_null_exit_code(self) -> None:
        self._create_task(
            checks=[
                {
                    "name": "unstartable",
                    "argv": ["harness-command-that-does-not-exist"],
                    "required": True,
                }
            ]
        )
        run = verify_task("TASK-SUMMARY", cwd=self.repository)

        result = self._run_show("TASK-SUMMARY", run.run_id)
        summary = self._success_summary(result)

        self.assertEqual(summary["mechanical_result"], "fail")
        self.assertFalse(summary["required_checks_pass"])
        self.assertEqual(
            summary["checks"],
            [
                {
                    "exit_code": None,
                    "name": "unstartable",
                    "passed": False,
                    "required": True,
                    "timed_out": False,
                }
            ],
        )
        self.assertIn('"exit_code": null', result.stdout)

    def test_source_instability_is_valid_summary_state(self) -> None:
        self._create_task(
            checks=[
                self._python_check(
                    "mutate-source",
                    "from pathlib import Path; "
                    "Path('src/example.txt').write_text('during check\\n', encoding='utf-8')",
                )
            ]
        )
        run = verify_task("TASK-SUMMARY", cwd=self.repository)

        summary = self._success_summary(self._run_show("TASK-SUMMARY", run.run_id))

        self.assertEqual(summary["mechanical_result"], "fail")
        self.assertTrue(summary["scope_pass"])
        self.assertTrue(summary["required_checks_pass"])
        self.assertFalse(summary["source_stable_during_checks"])
        self.assertTrue(summary["checks"][0]["passed"])

    def test_explicit_run_id_selects_only_the_requested_run(self) -> None:
        self._create_task()
        self._write("src/example.txt", "first candidate\n")
        first = verify_task("TASK-SUMMARY", cwd=self.repository)
        self._write("src/example.txt", "second candidate\n")
        second = verify_task("TASK-SUMMARY", cwd=self.repository)

        first_summary = self._success_summary(
            self._run_show("TASK-SUMMARY", first.run_id)
        )
        second_summary = self._success_summary(
            self._run_show("TASK-SUMMARY", second.run_id)
        )

        self.assertEqual(first_summary["run_id"], first.run_id)
        self.assertEqual(second_summary["run_id"], second.run_id)
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertNotEqual(
            first_summary["evidence_sha256"],
            second_summary["evidence_sha256"],
        )

    def test_parser_requires_explicit_run_id_and_rejects_latest_selection(self) -> None:
        for arguments in (
            ("run", "show", "TASK-SUMMARY"),
            ("run", "show", "TASK-SUMMARY", "--latest"),
        ):
            with self.subTest(arguments=arguments):
                result = self._run_cli(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("usage:", result.stderr)
                self.assertIn("error:", result.stderr)

    def test_identity_repository_and_missing_evidence_exit_contracts(self) -> None:
        invalid_id = self._run_show("TASK-SUMMARY", "../invalid-run")
        self.assertEqual(invalid_id.returncode, 2)
        self.assertEqual(invalid_id.stdout, "")
        self.assertTrue(invalid_id.stderr.startswith("error: "))

        missing_task = self._run_show("TASK-MISSING", "missing-run")
        self.assertEqual(missing_task.returncode, 2)
        self.assertEqual(missing_task.stdout, "")
        self.assertTrue(missing_task.stderr.startswith("error: "))

        self._create_task()
        missing_run = self._run_show("TASK-SUMMARY", "missing-run")
        self.assertEqual(missing_run.returncode, 8)
        self.assertEqual(missing_run.stdout, "")
        self.assertTrue(missing_run.stderr.startswith("error: "))

        outside_repository = self.root / "not-a-repository"
        outside_repository.mkdir()
        repository_error = self._run_show(
            "TASK-SUMMARY",
            "missing-run",
            cwd=outside_repository,
        )
        self.assertEqual(repository_error.returncode, 3)
        self.assertEqual(repository_error.stdout, "")
        self.assertTrue(repository_error.stderr.startswith("error: "))

    def test_task_run_identity_mismatch_returns_exit_2(self) -> None:
        self._create_task(task_id="TASK-FIRST")
        self._create_task(task_id="TASK-SECOND")
        run = verify_task("TASK-FIRST", cwd=self.repository)
        copied_run = (
            self.repository
            / ".harness"
            / "evidence"
            / "TASK-SECOND"
            / run.run_id
        )
        copied_run.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(run.evidence_path, copied_run)

        result = self._run_show("TASK-SECOND", run.run_id)

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.startswith("error: "))

    def test_corrupt_and_unsupported_evidence_return_exit_8(self) -> None:
        self._create_task()
        corrupt = verify_task("TASK-SUMMARY", cwd=self.repository)
        (corrupt.evidence_path / "verification.json").write_text(
            "{",
            encoding="utf-8",
        )
        corrupt_result = self._run_show("TASK-SUMMARY", corrupt.run_id)
        self.assertEqual(corrupt_result.returncode, 8)
        self.assertEqual(corrupt_result.stdout, "")
        self.assertTrue(corrupt_result.stderr.startswith("error: "))

        unsupported = verify_task("TASK-SUMMARY", cwd=self.repository)
        verification_path = unsupported.evidence_path / "verification.json"
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        verification["schema_version"] = 1
        verification_path.write_text(json.dumps(verification), encoding="utf-8")
        unsupported_result = self._run_show("TASK-SUMMARY", unsupported.run_id)
        self.assertEqual(unsupported_result.returncode, 8)
        self.assertEqual(unsupported_result.stdout, "")
        self.assertTrue(unsupported_result.stderr.startswith("error: "))

    def test_manifest_digest_mismatch_returns_exit_8(self) -> None:
        self._create_task()
        run = verify_task("TASK-SUMMARY", cwd=self.repository)
        diff_path = run.evidence_path / "diff.patch"
        diff_path.write_bytes(diff_path.read_bytes() + b"tampered\n")

        result = self._run_show("TASK-SUMMARY", run.run_id)

        self.assertEqual(result.returncode, 8)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.startswith("error: "))

    @unittest.skipUnless(os.name == "posix", "symlink safety coverage requires POSIX")
    def test_unsafe_run_directory_returns_exit_8(self) -> None:
        self._create_task()
        run = verify_task("TASK-SUMMARY", cwd=self.repository)
        unsafe_run = run.evidence_path.parent / "unsafe-run"
        unsafe_run.symlink_to(run.evidence_path, target_is_directory=True)

        result = self._run_show("TASK-SUMMARY", "unsafe-run")

        self.assertEqual(result.returncode, 8)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.startswith("error: "))


if __name__ == "__main__":
    unittest.main()
