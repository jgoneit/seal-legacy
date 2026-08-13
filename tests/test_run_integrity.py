"""Regression coverage for the canonical stored-Run integrity boundary."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path, PurePosixPath


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from harness.bundle import BundleEvidenceError, create_verification_bundle
from harness.evidence import (
    CompletionEvidenceError,
    CompletionRequiredCheckFailureError,
    complete_task,
    verify_task,
)
from harness.run_validator import (
    RunEvidenceError,
    RunValidationError,
    ValidatedRun,
    validate_run,
)
from harness.task import create_task
from harness.verdict import VerdictEvidenceError, record_verdict
from tests._evidence_fixtures import rewrite_failed_check_as_timeout


class CanonicalRunIntegrityTests(unittest.TestCase):
    """Validate only persisted Evidence, including normal failed outcomes."""

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
    def _check(
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
        task_id: str = "TASK-RUN",
        checks: list[dict[str, object]] | None = None,
        scope: list[str] | None = None,
        verifier_required: bool = False,
    ) -> None:
        specification = {
            "schema_version": 1,
            "id": task_id,
            "type": "test",
            "objective": "Exercise canonical Run integrity validation.",
            "scope": ["src"] if scope is None else scope,
            "checks": checks if checks is not None else [self._check("ok", "print('ok')")],
            "risk": "low",
            "verifier": {"required": verifier_required},
        }
        source = self.root / f"{task_id}.json"
        source.write_text(json.dumps(specification), encoding="utf-8")
        create_task(source, cwd=self.repository)

    def _run(self, task_id: str = "TASK-RUN"):
        return verify_task(task_id, cwd=self.repository)

    def _valid_run(self, *, task_id: str = "TASK-RUN"):
        self._create_task(task_id=task_id)
        self._write("src/example.txt", "after\n")
        return self._run(task_id)

    def _document(self, path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_document(self, path: Path, value: object) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def _verdict_file(self, task_id: str, run_id: str) -> Path:
        path = self.root / f"{task_id}-{run_id}-verdict.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "task_id": task_id,
                    "run_id": run_id,
                    "verifier": {
                        "kind": "manual",
                        "runner": "human",
                        "model": None,
                        "fresh_context": True,
                    },
                    "verdict": "pass",
                    "summary": "Manual integrity coverage verdict.",
                    "findings": [],
                    "reviewed_at": "2026-07-17T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_validates_passing_optional_failure_without_or_with_verdict(self) -> None:
        self._create_task(
            checks=[
                self._check("required", "print('ok')"),
                self._check("optional", "import sys; sys.exit(2)", required=False),
            ],
            verifier_required=True,
        )
        self._write("src/example.txt", "after\n")
        run = self._run()

        before_verdict = validate_run("TASK-RUN", run.run_id, cwd=self.repository)

        self.assertIsInstance(before_verdict, ValidatedRun)
        self.assertTrue(before_verdict.scope_pass)
        self.assertTrue(before_verdict.required_checks_pass)
        self.assertEqual(before_verdict.mechanical_result, "pass")
        self.assertFalse(before_verdict.check_records[1]["passed"])
        self.assertEqual(before_verdict.task_id, "TASK-RUN")
        self.assertFalse((run.evidence_path / "verdict.json").exists())

        record_verdict(
            "TASK-RUN",
            run.run_id,
            self._verdict_file("TASK-RUN", run.run_id),
            cwd=self.repository,
        )
        after_verdict = validate_run("TASK-RUN", run.run_id, cwd=self.repository)

        self.assertEqual(after_verdict.mechanical_result, "pass")
        self.assertTrue((run.evidence_path / "verdict.json").is_file())

    def test_validates_required_check_failure_and_allows_bundle_and_verdict(self) -> None:
        self._create_task(checks=[self._check("fail", "import sys; sys.exit(12)")])
        self._write("src/example.txt", "after\n")
        run = self._run()

        validated = validate_run("TASK-RUN", run.run_id, cwd=self.repository)

        self.assertIsInstance(validated, ValidatedRun)
        self.assertFalse(validated.required_checks_pass)
        self.assertEqual(validated.mechanical_result, "fail")
        bundle = create_verification_bundle(
            "TASK-RUN", run.run_id, self.root / "failed-bundle", cwd=self.repository
        )
        self.assertTrue(bundle.manifest_path.is_file())
        record = record_verdict(
            "TASK-RUN",
            run.run_id,
            self._verdict_file("TASK-RUN", run.run_id),
            cwd=self.repository,
        )
        self.assertTrue(record.snapshot_path.is_file())
        with self.assertRaises(CompletionRequiredCheckFailureError):
            complete_task("TASK-RUN", run.run_id, cwd=self.repository)

    def test_validates_timeout_as_a_failed_but_noncorrupt_run(self) -> None:
        self._create_task(
            checks=[
                self._check(
                    "timeout",
                    "import sys; sys.exit(24)",
                    timeout_seconds=1,
                )
            ]
        )
        run = self._run()
        rewrite_failed_check_as_timeout(
            run.evidence_path,
            task_id="TASK-RUN",
            run_id=run.run_id,
        )

        validated = validate_run("TASK-RUN", run.run_id, cwd=self.repository)

        self.assertIsInstance(validated, ValidatedRun)
        self.assertTrue(validated.check_records[0]["timed_out"])
        self.assertFalse(validated.required_checks_pass)
        self.assertEqual(validated.mechanical_result, "fail")

    def test_validates_scope_violation_as_a_failed_but_noncorrupt_run(self) -> None:
        self._create_task()
        self._write("docs/outside.txt", "outside scope\n")
        run = self._run()

        validated = validate_run("TASK-RUN", run.run_id, cwd=self.repository)

        self.assertIsInstance(validated, ValidatedRun)
        self.assertFalse(validated.scope_pass)
        self.assertEqual(validated.mechanical_result, "fail")
        self.assertEqual(
            [change["path"] for change in validated.verification["scope_violations"]],
            ["docs/outside.txt"],
        )

    def test_validates_cross_boundary_rename_as_scope_violation(self) -> None:
        self._create_task()
        (self.repository / "docs").mkdir()
        self._git("mv", "src/example.txt", "docs/example.txt")
        run = self._run()

        validated = validate_run("TASK-RUN", run.run_id, cwd=self.repository)

        self.assertFalse(validated.scope_pass)
        self.assertEqual(validated.mechanical_result, "fail")
        self.assertEqual(
            [change["path"] for change in validated.verification["scope_violations"]],
            ["docs/example.txt"],
        )
        self.assertEqual(
            validated.verification["scope_violations"][0]["previous_path"],
            "src/example.txt",
        )

    def test_validated_run_is_deeply_immutable_and_independent(self) -> None:
        run = self._valid_run()
        validated = validate_run("TASK-RUN", run.run_id, cwd=self.repository)

        with self.assertRaises(FrozenInstanceError):
            validated.task_id = "OTHER"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            validated.task["objective"] = "tampered"
        with self.assertRaises(TypeError):
            validated.task["checks"].append({})
        with self.assertRaises(TypeError):
            validated.check_records[0]["passed"] = False

        reread = validate_run("TASK-RUN", run.run_id, cwd=self.repository)
        self.assertEqual(reread.task["objective"], "Exercise canonical Run integrity validation.")
        self.assertTrue(reread.check_records[0]["passed"])

    def test_validated_log_paths_are_exactly_the_recorded_check_logs(self) -> None:
        run = self._valid_run()
        validated = validate_run("TASK-RUN", run.run_id, cwd=self.repository)

        expected = tuple(
            PurePosixPath(record[field])
            for record in validated.check_records
            for field in ("stdout_path", "stderr_path")
        )

        self.assertEqual(validated.log_paths, expected)
        self.assertEqual(len(validated.log_paths), len(set(validated.log_paths)))
        self.assertNotIn(PurePosixPath("task.json"), validated.log_paths)

    def test_reads_validated_log_bytes_without_text_decoding(self) -> None:
        stdout = b"stdout-before-\xff\x00-after\n"
        stderr = b"stderr-before-\xfe\x80-after\n"
        program = (
            "import os; "
            f"os.write(1, {stdout!r}); "
            f"os.write(2, {stderr!r})"
        )
        self._create_task(checks=[self._check("raw-bytes", program)])
        self._write("src/example.txt", "after\n")
        run = self._run()
        validated = validate_run("TASK-RUN", run.run_id, cwd=self.repository)
        record = validated.check_records[0]

        self.assertEqual(
            validated.read_log_bytes(PurePosixPath(record["stdout_path"])),
            stdout,
        )
        self.assertEqual(
            validated.read_log_bytes(PurePosixPath(record["stderr_path"])),
            stderr,
        )

    def test_log_reader_rejects_paths_outside_validated_log_membership(self) -> None:
        run = self._valid_run()
        validated = validate_run("TASK-RUN", run.run_id, cwd=self.repository)

        for path in (
            PurePosixPath("task.json"),
            PurePosixPath("../outside.log"),
            PurePosixPath("/tmp/outside.log"),
        ):
            with self.subTest(path=path):
                with self.assertRaisesRegex(
                    RunEvidenceError,
                    "is not a validated check log",
                ):
                    validated.read_log_bytes(path)

        with self.assertRaisesRegex(
            TypeError,
            "relative_path must be a PurePosixPath",
        ):
            validated.read_log_bytes("task.json")  # type: ignore[arg-type]

    @unittest.skipUnless(os.name == "posix", "symlink escape coverage requires POSIX")
    def test_log_reader_rejects_external_symlink_swap_after_validation(self) -> None:
        run = self._valid_run()
        validated = validate_run("TASK-RUN", run.run_id, cwd=self.repository)
        relative_path = validated.log_paths[0]
        log_path = validated.evidence_path.joinpath(*relative_path.parts)
        outside = self.root / "outside-after-validation.log"
        outside.write_text("outside\n", encoding="utf-8")
        log_path.unlink()
        log_path.symlink_to(outside)

        with self.assertRaisesRegex(
            RunEvidenceError,
            "Could not read previously validated log file",
        ):
            validated.read_log_bytes(relative_path)

    @unittest.skipUnless(os.name == "posix", "symlink escape coverage requires POSIX")
    def test_log_reader_rejects_run_directory_swap_after_validation(self) -> None:
        run = self._valid_run()
        validated = validate_run("TASK-RUN", run.run_id, cwd=self.repository)
        relative_path = validated.log_paths[0]
        original_run = self.root / "original-validated-run"
        outside_run = self.root / "outside-run-after-validation"
        outside_log = outside_run.joinpath(*relative_path.parts)
        outside_log.parent.mkdir(parents=True)
        outside_log.write_text("outside\n", encoding="utf-8")
        validated.evidence_path.rename(original_run)
        validated.evidence_path.symlink_to(outside_run, target_is_directory=True)

        with self.assertRaisesRegex(
            RunEvidenceError,
            "Could not read previously validated log file",
        ):
            validated.read_log_bytes(relative_path)

    def test_rejects_required_file_and_json_failures(self) -> None:
        run = self._valid_run()
        task_path = run.evidence_path / "task.json"
        task_path.unlink()
        with self.assertRaises(RunEvidenceError):
            validate_run("TASK-RUN", run.run_id, cwd=self.repository)

        run = self._valid_run(task_id="TASK-MALFORMED")
        (run.evidence_path / "checks.json").write_text("{", encoding="utf-8")
        with self.assertRaises(RunValidationError):
            validate_run("TASK-MALFORMED", run.run_id, cwd=self.repository)

    def test_rejects_identity_and_task_snapshot_mismatches(self) -> None:
        run = self._valid_run()
        verification_path = run.evidence_path / "verification.json"
        original_verification = self._document(verification_path)

        for field, value in (("task_id", "OTHER-TASK"), ("run_id", "other-run")):
            with self.subTest(field=field):
                verification = copy.deepcopy(original_verification)
                verification[field] = value
                self._write_document(verification_path, verification)
                with self.assertRaises(RunValidationError):
                    validate_run("TASK-RUN", run.run_id, cwd=self.repository)
        self._write_document(verification_path, original_verification)

        task_path = run.evidence_path / "task.json"
        task = self._document(task_path)
        task["objective"] = "Run snapshot differs from the saved Task."
        self._write_document(task_path, task)
        with self.assertRaises(RunValidationError):
            validate_run("TASK-RUN", run.run_id, cwd=self.repository)

    def test_rejects_check_shape_and_identity_mismatches(self) -> None:
        run = self._valid_run()
        checks_path = run.evidence_path / "checks.json"
        original = self._document(checks_path)

        mutations = {
            "count": lambda value: value["checks"].clear(),
            "name": lambda value: value["checks"][0].__setitem__("name", "other"),
            "argv": lambda value: value["checks"][0].__setitem__("argv", ["other"]),
            "required": lambda value: value["checks"][0].__setitem__("required", False),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                document = copy.deepcopy(original)
                mutate(document)
                self._write_document(checks_path, document)
                with self.assertRaises(RunValidationError):
                    validate_run("TASK-RUN", run.run_id, cwd=self.repository)
        self._write_document(checks_path, original)

    def test_rejects_inconsistent_check_outcomes(self) -> None:
        run = self._valid_run()
        checks_path = run.evidence_path / "checks.json"
        original = self._document(checks_path)

        for name, mutate in (
            (
                "passed-with-nonzero-exit",
                lambda value: value["checks"][0].__setitem__("exit_code", 1),
            ),
            (
                "passed-and-timeout",
                lambda value: value["checks"][0].__setitem__("timed_out", True),
            ),
        ):
            with self.subTest(name=name):
                document = copy.deepcopy(original)
                mutate(document)
                self._write_document(checks_path, document)
                with self.assertRaisesRegex(RunValidationError, r"passed does not match"):
                    validate_run("TASK-RUN", run.run_id, cwd=self.repository)
        self._write_document(checks_path, original)

    def test_rejects_forged_mechanical_and_scope_results(self) -> None:
        run = self._valid_run()
        verification_path = run.evidence_path / "verification.json"
        original = self._document(verification_path)

        mutations = {
            "required-checks": lambda value: value.__setitem__("required_checks_pass", False),
            "mechanical-result": lambda value: value.__setitem__("mechanical_result", "fail"),
            "scope-pass": lambda value: value.__setitem__("scope_pass", False),
            "scope-violations": lambda value: value.__setitem__(
                "scope_violations", [value["changed_files"][0]]
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                document = copy.deepcopy(original)
                mutate(document)
                self._write_document(verification_path, document)
                with self.assertRaises(RunValidationError):
                    validate_run("TASK-RUN", run.run_id, cwd=self.repository)
        self._write_document(verification_path, original)

    def test_rejects_forged_baseline_product_changes_and_metadata(self) -> None:
        run = self._valid_run()
        changed_path = run.evidence_path / "changed-files.json"
        verification_path = run.evidence_path / "verification.json"
        original_changed = self._document(changed_path)
        original_verification = self._document(verification_path)

        changed = copy.deepcopy(original_changed)
        changed["baseline"] = "forged-baseline"
        self._write_document(changed_path, changed)
        with self.assertRaises(RunValidationError):
            validate_run("TASK-RUN", run.run_id, cwd=self.repository)
        self._write_document(changed_path, original_changed)

        verification = copy.deepcopy(original_verification)
        verification["changed_files"] = []
        self._write_document(verification_path, verification)
        with self.assertRaises(RunValidationError):
            validate_run("TASK-RUN", run.run_id, cwd=self.repository)
        self._write_document(verification_path, original_verification)

        metadata_change = next(
            change
            for change in original_changed["changes"]
            if change["path"].startswith(".harness/")
        )
        verification = copy.deepcopy(original_verification)
        verification["changed_files"].append(metadata_change)
        self._write_document(verification_path, verification)
        with self.assertRaises(RunValidationError):
            validate_run("TASK-RUN", run.run_id, cwd=self.repository)

    def test_rejects_unsafe_duplicate_and_missing_evidence_paths(self) -> None:
        run = self._valid_run()
        verification_path = run.evidence_path / "verification.json"
        original = self._document(verification_path)

        for name, mutate in (
            (
                "traversal",
                lambda value: value["evidence_files"].__setitem__(0, "../outside.log"),
            ),
            (
                "absolute",
                lambda value: value["evidence_files"].__setitem__(0, "/tmp/outside.log"),
            ),
            (
                "windows-drive-absolute",
                lambda value: value["evidence_files"].__setitem__(0, "C:/outside.log"),
            ),
            (
                "duplicate",
                lambda value: value["evidence_files"].append(value["evidence_files"][0]),
            ),
        ):
            with self.subTest(name=name):
                document = copy.deepcopy(original)
                mutate(document)
                self._write_document(verification_path, document)
                with self.assertRaises(RunValidationError):
                    validate_run("TASK-RUN", run.run_id, cwd=self.repository)
        self._write_document(verification_path, original)

        checks = self._document(run.evidence_path / "checks.json")
        for field in ("stdout_path", "stderr_path"):
            with self.subTest(field=field):
                path = run.evidence_path / checks["checks"][0][field]
                contents = path.read_bytes()
                path.unlink()
                with self.assertRaises(RunValidationError):
                    validate_run("TASK-RUN", run.run_id, cwd=self.repository)
                path.write_bytes(contents)

        checks_path = run.evidence_path / "checks.json"
        original_checks = self._document(checks_path)
        unlisted_log = run.evidence_path / "checks" / "unlisted.stdout"
        unlisted_log.write_text("unlisted\n", encoding="utf-8")
        changed_checks = copy.deepcopy(original_checks)
        changed_checks["checks"][0]["stdout_path"] = "checks/unlisted.stdout"
        self._write_document(checks_path, changed_checks)
        with self.assertRaises(RunValidationError):
            validate_run("TASK-RUN", run.run_id, cwd=self.repository)

    @unittest.skipUnless(os.name == "posix", "directory symlink coverage requires POSIX")
    def test_rejects_evidence_directory_symlink_escape(self) -> None:
        run = self._valid_run()
        outside_run = self.root / "outside-run"
        run.evidence_path.rename(outside_run)
        run.evidence_path.symlink_to(outside_run, target_is_directory=True)

        with self.assertRaises(RunValidationError):
            validate_run("TASK-RUN", run.run_id, cwd=self.repository)

    @unittest.skipUnless(os.name == "posix", "symlink escape coverage requires POSIX")
    def test_rejects_evidence_symlink_escape(self) -> None:
        run = self._valid_run()
        checks_path = run.evidence_path / "checks.json"
        checks = self._document(checks_path)
        log_path = run.evidence_path / checks["checks"][0]["stdout_path"]
        outside = self.root / "outside.log"
        outside.write_text("outside\n", encoding="utf-8")
        log_path.unlink()
        log_path.symlink_to(outside)

        with self.assertRaises(RunValidationError):
            validate_run("TASK-RUN", run.run_id, cwd=self.repository)

    def test_all_consumers_reject_the_same_corrupt_run(self) -> None:
        run = self._valid_run()
        checks_path = run.evidence_path / "checks.json"
        checks = self._document(checks_path)
        checks["checks"][0]["passed"] = False
        self._write_document(checks_path, checks)

        with self.assertRaises(CompletionEvidenceError):
            complete_task("TASK-RUN", run.run_id, cwd=self.repository)
        with self.assertRaises(BundleEvidenceError):
            create_verification_bundle(
                "TASK-RUN", run.run_id, self.root / "corrupt-bundle", cwd=self.repository
            )
        with self.assertRaises(VerdictEvidenceError):
            record_verdict(
                "TASK-RUN",
                run.run_id,
                self._verdict_file("TASK-RUN", run.run_id),
                cwd=self.repository,
            )
