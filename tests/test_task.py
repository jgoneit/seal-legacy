"""Task Spec validation, persistence, and CLI tests."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from harness import cli
from harness.task import (
    TaskAlreadyExistsError,
    TaskValidationError,
    create_task,
    normalize_task_spec,
)

try:
    from jsonschema import Draft202012Validator
except ImportError:  # The test extra keeps this out of the runtime dependency set.
    Draft202012Validator = None


CATALOG = {
    "schema_version": 1,
    "checks": [
        {
            "name": "unit-test",
            "argv": ["python3", "-m", "unittest", "discover", "-s", "tests"],
            "required": True,
            "timeout_seconds": 60,
        }
    ],
}


def task_spec() -> dict[str, object]:
    """Return a valid Task Spec that refers to the repository catalog."""
    return {
        "schema_version": 1,
        "id": "TASK-001",
        "type": "bugfix",
        "objective": "Prevent duplicate notifications.",
        "scope": ["./src//harness/", "tests\\unit"],
        "checks": ["unit-test"],
        "risk": "medium",
        "verifier": {"required": True, "preferred_runner": "grok"},
    }


@contextlib.contextmanager
def change_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class TaskSpecTests(unittest.TestCase):
    """Exercise the Task Spec boundary against a disposable Git repository."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary_directory.name) / "repository"
        self.repository.mkdir()
        self._git("init", "--quiet")
        (self.repository / "README.md").write_text("fixture\n", encoding="utf-8")
        self._git("add", "README.md")
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
        catalog_path = self.repository / ".harness" / "checks.json"
        catalog_path.parent.mkdir()
        catalog_path.write_text(json.dumps(CATALOG), encoding="utf-8")

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

    def _write_task_file(self, spec: dict[str, object]) -> Path:
        path = self.repository / "task.json"
        path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _create(self, spec: dict[str, object], *, force: bool = False) -> dict[str, object]:
        return create_task(
            self._write_task_file(spec),
            cwd=self.repository,
            force=force,
        )

    def test_creates_normalized_snapshot_from_catalog_reference(self) -> None:
        snapshot = self._create(task_spec())

        self.assertEqual(snapshot["scope"], ["src/harness", "tests/unit"])
        self.assertEqual(snapshot["checks"], CATALOG["checks"])
        stored = json.loads(
            (self.repository / ".harness" / "tasks" / "TASK-001.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(stored, snapshot)

    def test_creates_snapshot_from_an_inline_check_definition(self) -> None:
        spec = task_spec()
        spec["checks"] = [
            {
                "name": "syntax",
                "argv": ["python3", "-m", "compileall", "src"],
                "required": False,
            }
        ]

        snapshot = self._create(spec)

        self.assertEqual(snapshot["checks"], spec["checks"])

    def test_rejects_invalid_type(self) -> None:
        spec = task_spec()
        spec["type"] = "maintenance"
        with self.assertRaises(TaskValidationError):
            self._create(spec)

    def test_rejects_invalid_risk(self) -> None:
        spec = task_spec()
        spec["risk"] = "critical"
        with self.assertRaises(TaskValidationError):
            self._create(spec)

    def test_rejects_absolute_scope(self) -> None:
        spec = task_spec()
        spec["scope"] = ["/tmp/outside-repository"]
        with self.assertRaises(TaskValidationError):
            self._create(spec)

    def test_rejects_scope_traversal(self) -> None:
        spec = task_spec()
        spec["scope"] = ["src/../outside"]
        with self.assertRaises(TaskValidationError):
            self._create(spec)

    def test_rejects_empty_checks(self) -> None:
        spec = task_spec()
        spec["checks"] = []
        with self.assertRaises(TaskValidationError):
            self._create(spec)

    def test_rejects_string_argv(self) -> None:
        spec = task_spec()
        spec["checks"] = [
            {"name": "unit-test", "argv": "python3 -m unittest", "required": True}
        ]
        with self.assertRaises(TaskValidationError):
            self._create(spec)

    def test_rejects_duplicate_task_id_without_force(self) -> None:
        self._create(task_spec())
        with self.assertRaises(TaskAlreadyExistsError):
            self._create(task_spec())

    def test_force_overwrites_an_existing_snapshot_via_cli(self) -> None:
        source = self._write_task_file(task_spec())
        with change_directory(self.repository), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["task", "create", "--file", str(source)]), 0)

            replacement = task_spec()
            replacement["objective"] = "Prevent retried duplicate notifications."
            source.write_text(json.dumps(replacement), encoding="utf-8")
            self.assertEqual(
                cli.main(["task", "create", "--file", str(source), "--force"]), 0
            )

        stored = json.loads(
            (self.repository / ".harness" / "tasks" / "TASK-001.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(stored["objective"], replacement["objective"])

    def test_does_not_modify_the_source_file(self) -> None:
        source = self._write_task_file(task_spec())
        original = source.read_text(encoding="utf-8")

        create_task(source, cwd=self.repository)

        self.assertEqual(source.read_text(encoding="utf-8"), original)

    def test_records_the_current_head_as_baseline(self) -> None:
        snapshot = self._create(task_spec())
        self.assertEqual(snapshot["baseline"], self._git("rev-parse", "HEAD"))

    def test_rejects_unknown_catalog_reference(self) -> None:
        spec = task_spec()
        spec["checks"] = ["missing-check"]
        with self.assertRaises(TaskValidationError):
            self._create(spec)

    def test_rejects_an_invalid_task_id(self) -> None:
        spec = task_spec()
        spec["id"] = "../TASK-001"
        with self.assertRaises(TaskValidationError):
            self._create(spec)

    def test_show_prints_the_stored_snapshot_via_cli(self) -> None:
        self._create(task_spec())
        output = io.StringIO()
        with change_directory(self.repository), contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(["task", "show", "TASK-001"]), 0)
        self.assertEqual(json.loads(output.getvalue())["id"], "TASK-001")


@unittest.skipUnless(Draft202012Validator, "install the test extra to run JSON Schema parity")
class TaskSchemaParityTests(unittest.TestCase):
    """Keep the dependency-free Python validator aligned with task.schema.json."""

    def test_python_validator_matches_json_schema_for_structural_cases(self) -> None:
        schema = json.loads(
            (PROJECT_ROOT / "schemas" / "task.schema.json").read_text(encoding="utf-8")
        )
        schema_validator = Draft202012Validator(schema)

        inline_check = {
            "name": "unit-test",
            "argv": ["python3", "-m", "unittest"],
            "required": True,
            "timeout_seconds": 60,
        }
        valid = task_spec()
        valid["checks"] = [inline_check]
        cases = {
            "valid": (valid, True),
            "invalid type": ({**valid, "type": "maintenance"}, False),
            "invalid risk": ({**valid, "risk": "critical"}, False),
            "empty checks": ({**valid, "checks": []}, False),
            "string argv": (
                {
                    **valid,
                    "checks": [
                        {**inline_check, "argv": "python3 -m unittest"},
                    ],
                },
                False,
            ),
            "absolute scope": ({**valid, "scope": ["/tmp/outside"]}, False),
            "scope traversal": ({**valid, "scope": ["src/../outside"]}, False),
            "invalid task id": ({**valid, "id": "../TASK-001"}, False),
            "unknown field": ({**valid, "extra": True}, False),
        }

        for label, (candidate, expected_valid) in cases.items():
            with self.subTest(label=label):
                schema_valid = not list(schema_validator.iter_errors(candidate))
                try:
                    normalize_task_spec(copy.deepcopy(candidate), {})
                except TaskValidationError:
                    python_valid = False
                else:
                    python_valid = True

                self.assertEqual(schema_valid, expected_valid)
                self.assertEqual(python_valid, expected_valid)
