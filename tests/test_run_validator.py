"""Regression coverage for the packaged canonical Verdict contract."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from importlib.resources import files
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from harness.run_validator import VerdictValidationError, validate_verdict


class VerdictRuntimeValidatorTests(unittest.TestCase):
    """Exercise Schema validation separately from Verdict file persistence."""

    @staticmethod
    def _document(
        *,
        verdict: str = "pass",
        findings: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "task_id": "TASK-VALIDATOR",
            "run_id": "RUN-VALIDATOR",
            "verifier": {
                "kind": "manual",
                "runner": "human",
                "model": None,
                "fresh_context": True,
            },
            "verdict": verdict,
            "summary": "Manual Verdict validation coverage.",
            "findings": [] if findings is None else findings,
            "reviewed_at": "2026-07-16T00:00:00Z",
        }

    @staticmethod
    def _finding(severity: str) -> dict[str, object]:
        return {
            "severity": severity,
            "code": "VERDICT-001",
            "title": "Validation finding",
            "detail": "Exercise one finding shape.",
            "path": "src/example.py",
            "line": 1,
        }

    def test_accepts_pass_fail_and_unable_with_all_severities(self) -> None:
        variants = (
            ("pass", [self._finding("note")]),
            ("fail", [self._finding("blocker")]),
            ("unable", [self._finding("warning")]),
        )

        for verdict, findings in variants:
            with self.subTest(verdict=verdict):
                snapshot = validate_verdict(self._document(verdict=verdict, findings=findings))
                self.assertEqual(snapshot["verdict"], verdict)
                self.assertEqual(snapshot["findings"][0]["severity"], findings[0]["severity"])

    def test_returns_an_independent_snapshot_without_mutating_input(self) -> None:
        value = self._document(findings=[self._finding("note")])
        original = copy.deepcopy(value)

        snapshot = validate_verdict(value)
        snapshot["verifier"]["runner"] = "changed"
        snapshot["findings"][0]["detail"] = "changed"

        self.assertEqual(value, original)
        self.assertIsNot(snapshot, value)

    def test_rejects_schema_contract_failures_with_json_paths(self) -> None:
        cases: list[tuple[str, dict[str, object], str]] = []

        unknown_field = self._document()
        unknown_field["unexpected"] = True
        cases.append(("unknown top-level field", unknown_field, r"\$"))

        missing_required = self._document()
        del missing_required["summary"]
        cases.append(("missing required field", missing_required, r"\$"))

        inconclusive = self._document(verdict="inconclusive")
        cases.append(("obsolete verdict", inconclusive, r"verdict"))

        unknown_severity = self._document(findings=[self._finding("critical")])
        cases.append(("unknown severity", unknown_severity, r"findings\[0\]\.severity"))

        empty_summary = self._document()
        empty_summary["summary"] = ""
        cases.append(("empty summary", empty_summary, r"summary"))

        invalid_timestamp = self._document()
        invalid_timestamp["reviewed_at"] = "not-a-date"
        cases.append(("invalid timestamp", invalid_timestamp, r"reviewed_at"))

        timezone_free_timestamp = self._document()
        timezone_free_timestamp["reviewed_at"] = "2026-07-16T00:00:00"
        cases.append(("timezone-free timestamp", timezone_free_timestamp, r"reviewed_at"))

        invalid_task_id = self._document()
        invalid_task_id["task_id"] = "-TASK"
        cases.append(("invalid task id", invalid_task_id, r"task_id"))

        invalid_run_id = self._document()
        invalid_run_id["run_id"] = "-RUN"
        cases.append(("invalid run id", invalid_run_id, r"run_id"))

        for name, value, path in cases:
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    VerdictValidationError,
                    rf"Verdict validation failed at {path}:",
                ):
                    validate_verdict(value)

    def test_rejects_expected_identity_mismatches(self) -> None:
        value = self._document()

        with self.assertRaisesRegex(VerdictValidationError, r"at task_id:"):
            validate_verdict(value, expected_task_id="TASK-OTHER")
        with self.assertRaisesRegex(VerdictValidationError, r"at run_id:"):
            validate_verdict(value, expected_run_id="RUN-OTHER")


class VerdictContractCoherenceTests(unittest.TestCase):
    """Keep human-authored contracts and packaged runtime resources synchronized."""

    def test_root_and_packaged_contract_resources_are_byte_identical(self) -> None:
        pairs = (
            (
                PROJECT_ROOT / "schemas" / "verdict.schema.json",
                PROJECT_ROOT / "src" / "harness" / "resources" / "verdict.schema.json",
            ),
            (
                PROJECT_ROOT / "prompts" / "verifier.md",
                PROJECT_ROOT / "src" / "harness" / "resources" / "verifier.md",
            ),
        )
        for root, packaged in pairs:
            with self.subTest(root=root.name):
                self.assertEqual(root.read_bytes(), packaged.read_bytes())

    def test_packaged_schema_and_prompt_are_available_as_resources(self) -> None:
        resource_root = files("harness").joinpath("resources")
        self.assertTrue(resource_root.joinpath("verdict.schema.json").is_file())
        self.assertTrue(resource_root.joinpath("verifier.md").is_file())

    def test_prompt_example_is_valid_canonical_verdict_json(self) -> None:
        prompt = (PROJECT_ROOT / "prompts" / "verifier.md").read_text(encoding="utf-8")
        start = prompt.index("\n{\n") + 1
        example, _ = json.JSONDecoder().raw_decode(prompt[start:])

        snapshot = validate_verdict(example)

        self.assertEqual(snapshot["verdict"], "pass")
        self.assertNotIn("inconclusive", prompt)
        self.assertNotIn('"finding"', prompt)
        self.assertNotIn('"evidence"', prompt)
        self.assertNotIn("blocker_summary", prompt)

    def test_sync_check_passes_for_the_repository_contracts(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/sync_contracts.py", "--check"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sync_script_copies_and_detects_drift_in_an_isolated_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "scripts" / "sync_contracts.py"
            script.parent.mkdir()
            shutil.copy(PROJECT_ROOT / "scripts" / "sync_contracts.py", script)
            canonical_schema = root / "schemas" / "verdict.schema.json"
            canonical_prompt = root / "prompts" / "verifier.md"
            canonical_schema.parent.mkdir()
            canonical_prompt.parent.mkdir()
            canonical_schema.write_text('{"schema": "canonical"}\n', encoding="utf-8")
            canonical_prompt.write_text("canonical prompt\n", encoding="utf-8")

            check = subprocess.run(
                [sys.executable, str(script), "--check"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(check.returncode, 1)

            sync = subprocess.run(
                [sys.executable, str(script)],
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(sync.returncode, 0, sync.stdout + sync.stderr)
            self.assertEqual(
                canonical_schema.read_bytes(),
                (root / "src" / "harness" / "resources" / "verdict.schema.json").read_bytes(),
            )
            self.assertEqual(
                canonical_prompt.read_bytes(),
                (root / "src" / "harness" / "resources" / "verifier.md").read_bytes(),
            )
