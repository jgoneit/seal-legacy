"""Integration coverage for Phase 1b mechanical verification evidence."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from inspect import signature
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from seal_legacy import cli
from seal_legacy.evidence import (
    EvidenceRepositoryError,
    atomic_write_json,
    create_evidence_directory,
    verify_task,
)
from seal_legacy.task import create_task

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - exercised when the optional test extra is absent.
    Draft202012Validator = None
    FormatChecker = None


@contextlib.contextmanager
def change_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class VerificationEvidenceTests(unittest.TestCase):
    """Run saved Tasks against disposable repositories and inspect evidence."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self._git("init", "--quiet")
        self._write(".seal/checks.json", '{"checks": []}\n')
        self._write("src/example.txt", "before\n")
        self._git("add", ".")
        self._git(
            "-c",
            "user.name=Seal Legacy Test",
            "-c",
            "user.email=seal-test@example.invalid",
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

    def _create_task(
        self,
        checks: list[dict[str, object]],
        *,
        task_id: str = "TASK-VERIFY",
        scope: list[str] | None = None,
    ) -> None:
        specification = {
            "schema_version": 1,
            "id": task_id,
            "type": "test",
            "objective": "Exercise mechanical verification evidence.",
            "scope": ["src"] if scope is None else scope,
            "checks": checks,
            "risk": "low",
            "verifier": {"required": False},
        }
        source = self.root / f"{task_id}.json"
        source.write_text(json.dumps(specification), encoding="utf-8")
        create_task(source, cwd=self.repository)

    @staticmethod
    def _python_check(
        name: str,
        program: str,
        *,
        required: bool,
        timeout_seconds: int | None = None,
        arguments: list[str] | None = None,
    ) -> dict[str, object]:
        check: dict[str, object] = {
            "name": name,
            "argv": [sys.executable, "-c", program, *(arguments or [])],
            "required": required,
        }
        if timeout_seconds is not None:
            check["timeout_seconds"] = timeout_seconds
        return check

    def _check_records(self, evidence_path: Path) -> list[dict[str, object]]:
        return json.loads((evidence_path / "checks.json").read_text(encoding="utf-8"))["checks"]

    def test_required_check_success_writes_complete_evidence_set(self) -> None:
        self._create_task(
            [
                self._python_check("first", "print('first')", required=True),
                self._python_check("second", "print('second')", required=True),
            ]
        )
        self._write("src/example.txt", "after\n")

        run = verify_task("TASK-VERIFY", cwd=self.repository)

        self.assertTrue(run.verification["required_checks_pass"])
        self.assertTrue(run.verification["scope_pass"])
        self.assertEqual(run.verification["mechanical_result"], "pass")
        self.assertNotIn("complete", run.verification)
        self.assertEqual(
            [record["name"] for record in self._check_records(run.evidence_path)],
            ["first", "second"],
        )
        required_record_fields = {
            "name",
            "argv",
            "cwd",
            "started_at",
            "finished_at",
            "duration_seconds",
            "effective_timeout",
            "exit_code",
            "timed_out",
            "stdout_path",
            "stderr_path",
            "required",
            "passed",
        }
        first_record = self._check_records(run.evidence_path)[0]
        self.assertEqual(required_record_fields, set(first_record))
        self.assertEqual(first_record["cwd"], str(self.repository.resolve()))
        self.assertEqual(first_record["effective_timeout"], 300)
        self.assertLessEqual(first_record["started_at"], first_record["finished_at"])
        expected = {
            "task.json",
            "changed-files.json",
            "diff.patch",
            "checks.json",
            "source-before-checks.json",
            "source-after-checks.json",
            "verification.json",
        }
        evidence_files = set(run.verification["evidence_files"])
        self.assertTrue(expected <= evidence_files)
        for relative_path in evidence_files:
            self.assertTrue((run.evidence_path / relative_path).is_file(), relative_path)
        changed_files = json.loads(
            (run.evidence_path / "changed-files.json").read_text(encoding="utf-8")
        )
        self.assertIn("src/example.txt", {change["path"] for change in changed_files["changes"]})
        self.assertIn("src/example.txt", (run.evidence_path / "diff.patch").read_text(encoding="utf-8"))

    def test_evidence_does_not_serialize_the_process_environment(self) -> None:
        environment_name = "SEAL_CORE_EVIDENCE_TEST_SECRET"
        environment_value = "must-not-be-serialized"
        previous = os.environ.get(environment_name)
        os.environ[environment_name] = environment_value
        try:
            self._create_task([self._python_check("ok", "print('ok')", required=True)])
            run = verify_task("TASK-VERIFY", cwd=self.repository)
        finally:
            if previous is None:
                os.environ.pop(environment_name, None)
            else:
                os.environ[environment_name] = previous

        json_evidence = [
            "task.json",
            "changed-files.json",
            "checks.json",
            "source-before-checks.json",
            "source-after-checks.json",
            "verification.json",
        ]
        for relative_path in json_evidence:
            contents = (run.evidence_path / relative_path).read_text(encoding="utf-8")
            self.assertNotIn(environment_name, contents)
            self.assertNotIn(environment_value, contents)

    def test_required_check_failure_makes_mechanical_result_fail(self) -> None:
        self._create_task(
            [
                self._python_check("failing", "import sys; sys.exit(7)", required=True),
                self._python_check("after-failure", "print('still ran')", required=True),
            ]
        )

        run = verify_task("TASK-VERIFY", cwd=self.repository)

        records = self._check_records(run.evidence_path)
        record = records[0]
        self.assertFalse(record["passed"])
        self.assertEqual(record["exit_code"], 7)
        self.assertTrue(record["required"])
        self.assertTrue(records[1]["passed"])
        self.assertEqual([record["name"] for record in records], ["failing", "after-failure"])
        self.assertFalse(run.verification["required_checks_pass"])
        self.assertEqual(run.verification["mechanical_result"], "fail")

    def test_optional_check_failure_is_recorded_without_failing_required_result(self) -> None:
        self._create_task(
            [
                self._python_check("required", "print('ok')", required=True),
                self._python_check("optional", "import sys; sys.exit(3)", required=False),
            ]
        )

        run = verify_task("TASK-VERIFY", cwd=self.repository)

        records = self._check_records(run.evidence_path)
        self.assertTrue(records[0]["passed"])
        self.assertFalse(records[1]["passed"])
        self.assertFalse(records[1]["required"])
        self.assertTrue(run.verification["required_checks_pass"])
        self.assertEqual(run.verification["mechanical_result"], "pass")

    def test_scope_violation_makes_mechanical_result_fail(self) -> None:
        self._create_task([self._python_check("ok", "print('ok')", required=True)])
        self._write("docs/outside.txt", "out of scope\n")

        run = verify_task("TASK-VERIFY", cwd=self.repository)

        self.assertFalse(run.verification["scope_pass"])
        self.assertEqual(
            [change["path"] for change in run.verification["scope_violations"]],
            ["docs/outside.txt"],
        )
        self.assertEqual(run.verification["mechanical_result"], "fail")

    def test_timeout_terminates_the_process_group_and_records_timeout(self) -> None:
        program = (
            "import subprocess, sys, time; "
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
            "print(child.pid, flush=True); time.sleep(30)"
        )
        self._create_task(
            [
                self._python_check(
                    "timeout",
                    program,
                    required=True,
                    timeout_seconds=1,
                )
            ]
        )

        started = time.monotonic()
        run = verify_task("TASK-VERIFY", cwd=self.repository)
        elapsed = time.monotonic() - started

        record = self._check_records(run.evidence_path)[0]
        self.assertTrue(record["timed_out"])
        self.assertFalse(record["passed"])
        self.assertLess(elapsed, 5.0)
        if os.name == "posix":
            child_pid = int(
                (run.evidence_path / str(record["stdout_path"])).read_text(encoding="utf-8").strip()
            )
            self._assert_process_is_gone(child_pid)

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_successful_check_reaps_background_process_group(self) -> None:
        program = (
            "import subprocess, sys; "
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
            "print(child.pid, flush=True)"
        )
        self._create_task([self._python_check("background", program, required=True)])

        run = verify_task("TASK-VERIFY", cwd=self.repository)

        record = self._check_records(run.evidence_path)[0]
        self.assertTrue(record["passed"])
        child_pid = int(
            (run.evidence_path / str(record["stdout_path"])).read_text(encoding="utf-8").strip()
        )
        self._assert_process_is_gone(child_pid)

    def _assert_process_is_gone(self, process_id: int) -> None:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                os.kill(process_id, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        self.fail(f"timed-out check child process still exists: {process_id}")

    def test_shell_metacharacter_stays_a_literal_argv_element(self) -> None:
        metacharacter = "; rm -rf /"
        self._create_task(
            [
                self._python_check(
                    "literal-argument",
                    "import sys; print(sys.argv[1])",
                    required=True,
                    arguments=[metacharacter],
                )
            ]
        )

        run = verify_task("TASK-VERIFY", cwd=self.repository)

        record = self._check_records(run.evidence_path)[0]
        stdout = (run.evidence_path / str(record["stdout_path"])).read_text(encoding="utf-8")
        self.assertEqual(record["argv"][-1], metacharacter)
        self.assertEqual(stdout, metacharacter + "\n")

    def test_json_atomic_write_removes_partial_temporary_file_on_failure(self) -> None:
        target = self.root / "atomic.json"
        target.write_text('{"previous": true}\n', encoding="utf-8")

        with self.assertRaises(TypeError):
            atomic_write_json(target, {"written_before_failure": True, "broken": object()})

        self.assertEqual(target.read_text(encoding="utf-8"), '{"previous": true}\n')
        self.assertEqual(list(self.root.glob(".atomic.json.*.tmp")), [])

    def test_run_ids_and_evidence_directories_are_unique(self) -> None:
        first_id, first_path = create_evidence_directory(self.repository, "TASK-VERIFY")
        second_id, second_path = create_evidence_directory(self.repository, "TASK-VERIFY")

        self.assertNotEqual(first_id, second_id)
        self.assertNotEqual(first_path, second_path)
        self.assertTrue(first_path.is_dir())
        self.assertTrue(second_path.is_dir())

    def test_large_stdout_is_streamed_to_evidence_file(self) -> None:
        byte_count = 2_000_000
        self._create_task(
            [
                self._python_check(
                    "large-stdout",
                    f"import sys; sys.stdout.write('x' * {byte_count})",
                    required=True,
                )
            ]
        )

        run = verify_task("TASK-VERIFY", cwd=self.repository)

        record = self._check_records(run.evidence_path)[0]
        self.assertTrue(record["passed"])
        self.assertEqual(
            (run.evidence_path / str(record["stdout_path"])).stat().st_size,
            byte_count,
        )

    def test_invalid_task_baseline_prevents_checks_and_evidence_directory(self) -> None:
        marker = self.root / "check-ran"
        program = (
            "from pathlib import Path; "
            f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')"
        )
        self._create_task([self._python_check("must-not-run", program, required=True)])
        task_path = self.repository / ".seal" / "tasks" / "TASK-VERIFY.json"
        task = json.loads(task_path.read_text(encoding="utf-8"))
        task["baseline"] = "missing-task-baseline"
        task_path.write_text(json.dumps(task), encoding="utf-8")

        with self.assertRaisesRegex(EvidenceRepositoryError, "does not resolve to a commit"):
            verify_task("TASK-VERIFY", cwd=self.repository)

        self.assertFalse(marker.exists())
        self.assertFalse((self.repository / ".seal" / "evidence" / "TASK-VERIFY").exists())

    def test_diff_patch_preserves_staged_change_reversed_in_worktree(self) -> None:
        self._create_task([self._python_check("ok", "print('ok')", required=True)])
        self._write("src/example.txt", "staged\n")
        self._git("add", "src/example.txt")
        self._write("src/example.txt", "before\n")

        run = verify_task("TASK-VERIFY", cwd=self.repository)

        changed = json.loads((run.evidence_path / "changed-files.json").read_text(encoding="utf-8"))
        sources = {
            change["source"]
            for change in changed["changes"]
            if change["path"] == "src/example.txt"
        }
        patch = (run.evidence_path / "diff.patch").read_text(encoding="utf-8")
        self.assertEqual(sources, {"staged", "unstaged"})
        self.assertIn("+staged", patch)

    def test_diff_patch_ignores_git_replace_refs(self) -> None:
        baseline = self._git("rev-parse", "HEAD")
        self._create_task([self._python_check("ok", "print('ok')", required=True)])
        self._write("src/example.txt", "after\n")
        self._git("add", "src/example.txt")
        self._git(
            "-c",
            "user.name=Seal Legacy Test",
            "-c",
            "user.email=seal-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "candidate",
        )
        candidate = self._git("rev-parse", "HEAD")
        self._git("replace", baseline, candidate)
        try:
            with_replace = verify_task("TASK-VERIFY", cwd=self.repository)
        finally:
            self._git("replace", "-d", baseline)
        without_replace = verify_task("TASK-VERIFY", cwd=self.repository)

        expected_changes = [
            change
            for change in with_replace.verification["changed_files"]
            if change["path"] == "src/example.txt"
        ]
        self.assertEqual(
            [(change["source"], change["status"]) for change in expected_changes],
            [("committed", "modified")],
        )
        self.assertEqual(
            with_replace.verification["changed_files"],
            without_replace.verification["changed_files"],
        )
        self.assertEqual(
            with_replace.verification["source_before_checks_sha256"],
            without_replace.verification["source_before_checks_sha256"],
        )
        self.assertEqual(
            with_replace.verification["source_after_checks_sha256"],
            without_replace.verification["source_after_checks_sha256"],
        )
        patch_with_replace = (with_replace.evidence_path / "diff.patch").read_bytes()
        patch_without_replace = (
            without_replace.evidence_path / "diff.patch"
        ).read_bytes()
        self.assertEqual(patch_with_replace, patch_without_replace)
        self.assertIn(b"-before\n", patch_with_replace)
        self.assertIn(b"+after\n", patch_with_replace)

    def test_large_diff_patch_is_written_to_evidence_file(self) -> None:
        byte_count = 1_000_000
        self._create_task([self._python_check("ok", "print('ok')", required=True)])
        self._write("src/example.txt", "x" * byte_count)

        run = verify_task("TASK-VERIFY", cwd=self.repository)

        self.assertGreater((run.evidence_path / "diff.patch").stat().st_size, byte_count)

    def test_atomic_json_escapes_lone_surrogates(self) -> None:
        target = self.root / "surrogate.json"
        path = "src/" + os.fsdecode(b"non-utf8-\xff.txt")

        atomic_write_json(target, {"path": path})

        contents = target.read_bytes()
        self.assertIn(b"\\udcff", contents)
        self.assertEqual(json.loads(contents)["path"], path)

    @unittest.skipUnless(os.name == "posix", "requires POSIX surrogateescaped Git paths")
    def test_non_utf8_git_path_writes_valid_json_evidence(self) -> None:
        self._create_task([self._python_check("ok", "print('ok')", required=True)])
        filename = os.fsdecode(b"non-utf8-\xff.txt")
        try:
            self._write(f"src/{filename}", b"changed\n")
        except OSError as error:
            self.skipTest(f"filesystem rejects non-UTF-8 paths: {error}")

        run = verify_task("TASK-VERIFY", cwd=self.repository)

        changed_bytes = (run.evidence_path / "changed-files.json").read_bytes()
        verification_bytes = (run.evidence_path / "verification.json").read_bytes()
        changed = json.loads(changed_bytes)
        verification = json.loads(verification_bytes)
        expected_path = f"src/{filename}"
        self.assertIn(b"\\udcff", changed_bytes)
        self.assertIn(b"\\udcff", verification_bytes)
        self.assertIn(expected_path, {change["path"] for change in changed["changes"]})
        self.assertIn(expected_path, {change["path"] for change in verification["changed_files"]})

    @unittest.skipUnless(os.name == "posix", "requires POSIX textconv command handling")
    def test_diff_collection_disables_textconv(self) -> None:
        marker = self.root / "textconv-ran"
        converter = self.root / "textconv.py"
        converter.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n"
            "print(Path(sys.argv[-1]).read_text(encoding='utf-8'))\n",
            encoding="utf-8",
        )
        self._write(".gitattributes", "src/example.txt diff=forbidden\n")
        self._git("add", ".gitattributes")
        self._git(
            "-c",
            "user.name=Seal Legacy Test",
            "-c",
            "user.email=seal-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "configure textconv",
        )
        self._git(
            "config",
            "diff.forbidden.textconv",
            f"{shlex.quote(sys.executable)} {shlex.quote(str(converter))}",
        )
        self._create_task([self._python_check("ok", "print('ok')", required=True)])
        self._write("src/example.txt", "after\n")

        verify_task("TASK-VERIFY", cwd=self.repository)

        self.assertFalse(marker.exists())

    def test_cli_verify_prints_run_id_and_uses_task_baseline(self) -> None:
        self._create_task([self._python_check("ok", "print('ok')", required=True)])
        task_baseline = self._git("rev-parse", "HEAD")
        self._write("src/committed.txt", "committed change\n")
        self._git("add", "src/committed.txt")
        self._git(
            "-c",
            "user.name=Seal Legacy Test",
            "-c",
            "user.email=seal-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "later change",
        )
        output = io.StringIO()

        with change_directory(self.repository), contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(["verify", "TASK-VERIFY"]), 0)

        response = json.loads(output.getvalue())
        self.assertEqual(set(response), {"evidence_path", "run_id"})
        evidence_path = Path(response["evidence_path"])
        verification = json.loads((evidence_path / "verification.json").read_text(encoding="utf-8"))
        self.assertEqual(response["run_id"], verification["run_id"])
        self.assertEqual(verification["baseline"], task_baseline)
        self.assertIn(
            "src/committed.txt",
            {change["path"] for change in verification["changed_files"]},
        )

    def test_cli_verify_rejects_removed_base_ref_option(self) -> None:
        self._create_task([self._python_check("ok", "print('ok')", required=True)])

        self.assertNotIn("base_ref", signature(verify_task).parameters)
        help_stdout = io.StringIO()
        with contextlib.redirect_stdout(help_stdout):
            with self.assertRaises(SystemExit) as help_exit:
                cli.main(["verify", "--help"])
        self.assertEqual(help_exit.exception.code, 0)
        self.assertNotIn("--base-ref", help_stdout.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                cli.main(["verify", "TASK-VERIFY", "--base-ref", "HEAD"])

        self.assertEqual(raised.exception.code, 2)
        self.assertFalse(
            (self.repository / ".seal" / "evidence" / "TASK-VERIFY").exists()
        )

    def test_verification_schema_top_level_fields_match_emitted_document(self) -> None:
        self._create_task([self._python_check("ok", "print('ok')", required=True)])

        run = verify_task("TASK-VERIFY", cwd=self.repository)
        schema = json.loads(
            (PROJECT_ROOT / "schemas" / "verification.schema.json").read_text(encoding="utf-8")
        )

        self.assertEqual(set(run.verification), set(schema["required"]))
        self.assertEqual(set(schema["properties"]), set(schema["required"]))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["schema_version"]["const"], 2)
        self.assertEqual(
            schema["properties"]["mechanical_result"]["enum"],
            ["pass", "fail"],
        )


@unittest.skipUnless(Draft202012Validator, "install the test extra to run JSON Schema parity")
class VerificationSchemaParityTests(unittest.TestCase):
    """Keep the saved verification document aligned with its published schema."""

    def test_saved_verification_document_matches_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            repository.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=repository, check=True)
            (repository / ".seal").mkdir()
            (repository / ".seal" / "checks.json").write_text('{"checks": []}\n')
            (repository / "src").mkdir()
            (repository / "src" / "example.txt").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repository, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Seal Legacy Test",
                    "-c",
                    "user.email=seal-test@example.invalid",
                    "commit",
                    "--quiet",
                    "-m",
                    "fixture",
                ],
                cwd=repository,
                check=True,
            )
            specification = {
                "schema_version": 1,
                "id": "TASK-SCHEMA",
                "type": "test",
                "objective": "Validate emitted evidence against its schema.",
                "scope": ["src"],
                "checks": [
                    {
                        "name": "ok",
                        "argv": [sys.executable, "-c", "print('ok')"],
                        "required": True,
                    }
                ],
                "risk": "low",
                "verifier": {"required": False},
            }
            task_file = root / "task.json"
            task_file.write_text(json.dumps(specification), encoding="utf-8")
            create_task(task_file, cwd=repository)
            run = verify_task("TASK-SCHEMA", cwd=repository)

            schema = json.loads(
                (PROJECT_ROOT / "schemas" / "verification.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            validator = Draft202012Validator(schema, format_checker=FormatChecker())
            errors = list(validator.iter_errors(run.verification))
            self.assertEqual(errors, [])

    def test_v1_style_verification_is_rejected(self) -> None:
        schema = json.loads(
            (PROJECT_ROOT / "schemas" / "verification.schema.json").read_text(
                encoding="utf-8"
            )
        )
        v1_style = {
            "schema_version": 1,
            "task_id": "TASK-V1",
            "run_id": "run-v1",
            "baseline": "0" * 40,
            "changed_files": [],
            "scope_pass": True,
            "scope_violations": [],
            "required_checks_pass": True,
            "mechanical_result": "pass",
            "evidence_files": [
                "task.json",
                "changed-files.json",
                "diff.patch",
                "checks.json",
                "verification.json",
            ],
            "timestamp": "2026-07-25T00:00:00Z",
            "duration": 0,
        }
        validator = Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        )

        self.assertNotEqual(list(validator.iter_errors(v1_style)), [])
