"""Integration coverage for Phase 2a manual verifier verdicts."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from harness import cli
from harness.evidence import verify_task
from harness.task import create_task
from harness.verdict import VerdictEvidenceError, VerdictInputError, record_verdict, show_verdict

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # pragma: no cover - exercised without the optional test extra.
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


class ManualVerdictTests(unittest.TestCase):
    """Record only locally supplied manual verdicts for disposable Task runs."""

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

    def _create_task(self, *, verifier_required: bool = False) -> None:
        specification = {
            "schema_version": 1,
            "id": "TASK-VERDICT",
            "type": "test",
            "objective": "Exercise manual verifier verdict storage.",
            "scope": ["src"],
            "checks": [
                {
                    "name": "ok",
                    "argv": [sys.executable, "-c", "print('ok')"],
                    "required": True,
                }
            ],
            "risk": "low",
            "verifier": {"required": verifier_required},
        }
        source = self.root / "task.json"
        source.write_text(json.dumps(specification), encoding="utf-8")
        create_task(source, cwd=self.repository)

    def _run(self) -> str:
        self._create_task()
        return verify_task("TASK-VERDICT", cwd=self.repository).run_id

    @staticmethod
    def _finding(severity: str) -> dict[str, object]:
        return {
            "severity": severity,
            "code": f"{severity.upper()}-001",
            "title": f"{severity} finding",
            "detail": "Manual verifier finding.",
            "path": "src/example.txt",
            "line": 1,
        }

    def _document(
        self,
        run_id: str,
        *,
        verdict: str = "pass",
        findings: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "task_id": "TASK-VERDICT",
            "run_id": run_id,
            "verifier": {
                "kind": "manual",
                "runner": "human",
                "model": None,
                "fresh_context": True,
            },
            "verdict": verdict,
            "summary": "Manual review complete.",
            "findings": [] if findings is None else findings,
            "reviewed_at": "2026-07-16T00:00:00Z",
        }

    def _write_verdict(self, document: dict[str, object], *, contents: str | None = None) -> Path:
        source = self.root / "verdict-input.json"
        if contents is None:
            contents = json.dumps(document, ensure_ascii=False, indent=4) + "\n"
        source.write_text(contents, encoding="utf-8")
        return source

    def test_pass_verdict_preserves_raw_and_show_returns_snapshot(self) -> None:
        run_id = self._run()
        document = self._document(run_id)
        source = self._write_verdict(document)
        raw = source.read_bytes()

        output = io.StringIO()
        with change_directory(self.repository), contextlib.redirect_stdout(output):
            self.assertEqual(
                cli.main(
                    [
                        "verifier",
                        "record",
                        "TASK-VERDICT",
                        "--run-id",
                        run_id,
                        "--file",
                        str(source),
                    ]
                ),
                0,
            )
        response = json.loads(output.getvalue())
        record = show_verdict("TASK-VERDICT", run_id, cwd=self.repository)

        self.assertEqual(record.raw_path.read_bytes(), raw)
        self.assertEqual(
            json.loads(record.snapshot_path.read_text(encoding="utf-8")),
            record.verdict,
        )
        self.assertEqual(Path(response["raw_verdict_path"]), record.raw_path)
        self.assertEqual(Path(response["verdict_path"]), record.snapshot_path)
        output = io.StringIO()
        with change_directory(self.repository), contextlib.redirect_stdout(output):
            self.assertEqual(
                cli.main(["verifier", "show", "TASK-VERDICT", "--run-id", run_id]),
                0,
            )
        self.assertEqual(json.loads(output.getvalue()), record.verdict)
        self.assertEqual(
            show_verdict("TASK-VERDICT", run_id, cwd=self.repository).verdict,
            record.verdict,
        )

    def test_record_accepts_blocker_warning_fail_and_unable_variants(self) -> None:
        run_id = self._run()
        variants = (
            ("blocker", "pass", [self._finding("blocker")], {"blocker": 1, "warning": 0, "note": 0}),
            ("warning-only", "pass", [self._finding("warning")], {"blocker": 0, "warning": 1, "note": 0}),
            ("fail", "fail", [], {"blocker": 0, "warning": 0, "note": 0}),
            ("unable", "unable", [], {"blocker": 0, "warning": 0, "note": 0}),
        )

        for name, verdict, findings, expected_counts in variants:
            with self.subTest(name=name):
                source = self._write_verdict(
                    self._document(run_id, verdict=verdict, findings=findings)
                )
                record = record_verdict("TASK-VERDICT", run_id, source, cwd=self.repository)
                self.assertEqual(record.verdict["verdict"], verdict)
                self.assertEqual(record.counts, expected_counts)

    def test_record_rejects_malformed_json(self) -> None:
        run_id = self._run()
        source = self._write_verdict(self._document(run_id), contents="{")

        with self.assertRaises(VerdictInputError):
            record_verdict("TASK-VERDICT", run_id, source, cwd=self.repository)

    def test_record_rejects_unknown_severity(self) -> None:
        run_id = self._run()
        source = self._write_verdict(
            self._document(run_id, findings=[self._finding("critical")])
        )

        with self.assertRaises(VerdictInputError):
            record_verdict("TASK-VERDICT", run_id, source, cwd=self.repository)

    def test_record_rejects_unknown_verdict(self) -> None:
        run_id = self._run()
        source = self._write_verdict(self._document(run_id, verdict="inconclusive"))

        with self.assertRaises(VerdictInputError):
            record_verdict("TASK-VERDICT", run_id, source, cwd=self.repository)

    def test_record_rejects_invalid_line_format(self) -> None:
        run_id = self._run()
        finding = self._finding("warning")
        finding["line"] = "1"
        source = self._write_verdict(self._document(run_id, findings=[finding]))

        with self.assertRaises(VerdictInputError):
            record_verdict("TASK-VERDICT", run_id, source, cwd=self.repository)

    def test_record_rejects_task_run_mismatch(self) -> None:
        run_id = self._run()
        document = self._document(run_id)
        document["run_id"] = "other-run"
        source = self._write_verdict(document)

        with self.assertRaises(VerdictInputError):
            record_verdict("TASK-VERDICT", run_id, source, cwd=self.repository)

    def test_show_rejects_valid_raw_verdict_tampering(self) -> None:
        run_id = self._run()
        source = self._write_verdict(self._document(run_id))
        record = record_verdict("TASK-VERDICT", run_id, source, cwd=self.repository)
        tampered = self._document(run_id)
        tampered["summary"] = "Raw Verdict was changed after recording."
        record.raw_path.write_text(json.dumps(tampered), encoding="utf-8")

        with self.assertRaises(VerdictEvidenceError):
            show_verdict("TASK-VERDICT", run_id, cwd=self.repository)

    def test_show_rejects_valid_snapshot_tampering(self) -> None:
        run_id = self._run()
        source = self._write_verdict(self._document(run_id))
        record = record_verdict("TASK-VERDICT", run_id, source, cwd=self.repository)
        tampered = self._document(run_id)
        tampered["summary"] = "Canonical Verdict was changed after recording."
        record.snapshot_path.write_text(json.dumps(tampered), encoding="utf-8")

        with self.assertRaises(VerdictEvidenceError):
            show_verdict("TASK-VERDICT", run_id, cwd=self.repository)


@unittest.skipUnless(Draft202012Validator, "install the test extra to run JSON Schema parity")
class VerdictSchemaParityTests(unittest.TestCase):
    """Keep the normalized manual verdict aligned with its public schema."""

    def test_recorded_snapshot_matches_verdict_schema(self) -> None:
        document = {
            "schema_version": 1,
            "task_id": "TASK-SCHEMA",
            "run_id": "RUN-SCHEMA",
            "verifier": {
                "kind": "manual",
                "runner": "human",
                "model": None,
                "fresh_context": True,
            },
            "verdict": "pass",
            "summary": "Schema validation.",
            "findings": [
                {
                    "severity": "note",
                    "code": "NOTE-001",
                    "title": "Schema note",
                    "detail": "The schema accepts a valid finding.",
                    "path": "src/example.txt",
                    "line": 1,
                }
            ],
            "reviewed_at": "2026-07-16T00:00:00Z",
        }
        schema = json.loads(
            (PROJECT_ROOT / "schemas" / "verdict.schema.json").read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(schema, format_checker=FormatChecker())

        self.assertEqual(list(validator.iter_errors(document)), [])
