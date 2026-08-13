"""Command-line entry point tests."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"


class CommandLineTests(unittest.TestCase):
    """Verify the console entry point target and module entry point."""

    def _run_command(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(SOURCE_ROOT)
        if existing_pythonpath:
            environment["PYTHONPATH"] += os.pathsep + existing_pythonpath

        return subprocess.run(
            [
                sys.executable,
                "-c",
                "from harness.cli import main; raise SystemExit(main())",
                *arguments,
            ],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )

    def assert_command_succeeds(self, *arguments: str) -> None:
        result = self._run_command(*arguments)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_console_entry_point_is_declared(self) -> None:
        pyproject = tomllib.loads(
            (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(pyproject["project"]["scripts"]["harness"], "harness.cli:main")

    def test_harness_help(self) -> None:
        result = self._run_command("--help")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn(
            "{task,verify,run,verifier,complete}",
            result.stdout,
        )

        task_help = self._run_command("task", "--help")
        self.assertEqual(task_help.returncode, 0, task_help.stderr)
        self.assertEqual(task_help.stderr, "")
        self.assertIn("{create,show}", task_help.stdout)

        run_help = self._run_command("run", "--help")
        self.assertEqual(run_help.returncode, 0, run_help.stderr)
        self.assertEqual(run_help.stderr, "")
        self.assertIn("{show}", run_help.stdout)

        verifier_help = self._run_command("verifier", "--help")
        self.assertEqual(verifier_help.returncode, 0, verifier_help.stderr)
        self.assertEqual(verifier_help.stderr, "")
        self.assertIn("{record,show,bundle}", verifier_help.stdout)

    def test_harness_version(self) -> None:
        result = self._run_command("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "0.3.0.dev0\n")
        self.assertEqual(result.stderr, "")

    def test_python_module_help(self) -> None:
        environment = os.environ.copy()
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(SOURCE_ROOT)
        if existing_pythonpath:
            environment["PYTHONPATH"] += os.pathsep + existing_pythonpath

        result = subprocess.run(
            [sys.executable, "-m", "harness", "--help"],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_core_facade_imports_are_order_independent(self) -> None:
        environment = os.environ.copy()
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(SOURCE_ROOT)
        if existing_pythonpath:
            environment["PYTHONPATH"] += os.pathsep + existing_pythonpath

        evidence_import = """
from harness.evidence import (
    COMPLETION_SCHEMA_VERSION,
    VERIFICATION_SCHEMA_VERSION,
    CompletionError,
    CompletionEvidenceError,
    CompletionInputError,
    CompletionRequiredCheckFailureError,
    CompletionRun,
    CompletionScopeViolationError,
    CompletionTimeoutError,
    CompletionVerifierEvidenceMissingError,
    CompletionVerifierRejectedError,
    EvidenceError,
    EvidenceRepositoryError,
    VerificationRun,
    atomic_write_bytes,
    atomic_write_json,
    complete_task,
    create_evidence_directory,
    generate_run_id,
    verify_task,
    write_diff_patch,
)
"""
        validator_import = """
from harness.run_validator import (
    RUN_EVIDENCE_SCHEMA_VERSION,
    RUN_ID_CHARACTERS,
    RunEvidenceError,
    RunIdentityError,
    RunValidationError,
    ValidatedRun,
    validate_run,
    validate_run_id,
)
"""
        private_boundary_assertions = """
import harness.bundle as bundle_module
import harness.run_manifest as manifest_module
import harness.run_validator as validator_module
import harness.verdict as verdict_module

assert callable(ValidatedRun.read_log_bytes)
assert not hasattr(validator_module, "validate_run_documents")
assert not hasattr(validator_module, "validate_task_snapshot")
assert not hasattr(manifest_module, "read_run_artifact_bytes")
assert not hasattr(manifest_module, "safe_run_relative_path")
assert not hasattr(bundle_module, "read_run_artifact_bytes")
assert "_read_run_artifact_bytes" not in bundle_module.__dict__
assert "_RunArtifactReadError" not in bundle_module.__dict__
assert not hasattr(verdict_module, "read_run_artifact_bytes")
"""
        for imports in (
            evidence_import + validator_import + private_boundary_assertions,
            validator_import + evidence_import + private_boundary_assertions,
        ):
            with self.subTest(first_import=imports.splitlines()[1]):
                result = subprocess.run(
                    [sys.executable, "-c", imports],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=environment,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_command_or_subcommand_is_invalid_input(self) -> None:
        for arguments in ((), ("task",), ("run",), ("verifier",)):
            with self.subTest(arguments=arguments):
                result = self._run_command(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("usage:", result.stderr)
                self.assertIn("error:", result.stderr)
