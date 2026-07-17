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
        self.assert_command_succeeds("--help")

    def test_harness_version(self) -> None:
        self.assert_command_succeeds("--version")

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

    def test_missing_command_or_subcommand_is_invalid_input(self) -> None:
        for arguments in ((), ("task",), ("verifier",)):
            with self.subTest(arguments=arguments):
                result = self._run_command(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("usage:", result.stderr)
                self.assertIn("error:", result.stderr)
