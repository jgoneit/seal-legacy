"""Regression coverage for the versioned mechanical Evidence Run manifest."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from seal_legacy.bundle import BundleEvidenceError, create_verification_bundle
from seal_legacy.evidence import CompletionEvidenceError, complete_task, verify_task
from seal_legacy.run_manifest import (
    RUN_MANIFEST_FILENAME,
    RunManifestError,
    create_run_manifest,
)
from seal_legacy.run_validator import RunValidationError, validate_run
from seal_legacy.task import create_task
from seal_legacy.verdict import VerdictEvidenceError, record_verdict, show_verdict
from tests._evidence_fixtures import rewrite_failed_check_as_timeout


class RunManifestTests(unittest.TestCase):
    """Cover the local consistency identifier for saved mechanical Evidence."""

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
        task_id: str = "TASK-MANIFEST",
        checks: list[dict[str, object]] | None = None,
        scope: list[str] | None = None,
    ) -> None:
        specification = {
            "schema_version": 1,
            "id": task_id,
            "type": "test",
            "objective": "Exercise versioned mechanical Evidence manifests.",
            "scope": ["src"] if scope is None else scope,
            "checks": checks if checks is not None else [self._check("ok", "print('ok')")],
            "risk": "low",
            "verifier": {"required": False},
        }
        source = self.root / f"{task_id}.json"
        source.write_text(json.dumps(specification), encoding="utf-8")
        create_task(source, cwd=self.repository)

    def _run(self, task_id: str = "TASK-MANIFEST"):
        return verify_task(task_id, cwd=self.repository)

    def _valid_run(self, *, task_id: str = "TASK-MANIFEST"):
        self._create_task(task_id=task_id)
        self._write("src/example.txt", "after\n")
        return self._run(task_id)

    @staticmethod
    def _document(path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_document(path: Path, value: object) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def _manifest_path(self, run_path: Path) -> Path:
        return run_path / RUN_MANIFEST_FILENAME

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
                    "summary": "Manifest regression verdict.",
                    "findings": [],
                    "reviewed_at": "2026-07-17T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_atomic_replace_failure_preserves_manifest_and_removes_partial(self) -> None:
        evidence_path = self.root / "manifest-write-failure"
        evidence_path.mkdir()
        evidence_file = evidence_path / "task.json"
        evidence_file.write_bytes(b'{"task":"fixture"}\n')
        manifest_path = evidence_path / RUN_MANIFEST_FILENAME
        previous_manifest = b"existing manifest sentinel\n"
        manifest_path.write_bytes(previous_manifest)

        with patch(
            "os.replace",
            side_effect=OSError("replace failed"),
        ):
            with self.assertRaisesRegex(
                RunManifestError,
                r"Could not write run-manifest\.json",
            ):
                create_run_manifest(
                    evidence_path,
                    task_id="TASK-MANIFEST",
                    run_id="run-write-failure",
                    evidence_files=(PurePosixPath("task.json"),),
                )

        self.assertEqual(manifest_path.read_bytes(), previous_manifest)
        self.assertEqual(
            list(evidence_path.glob(f".{RUN_MANIFEST_FILENAME}.*.tmp")),
            [],
        )
        self.assertEqual(evidence_file.read_bytes(), b'{"task":"fixture"}\n')

    def test_manifest_write_does_not_recreate_a_disappeared_run_directory(self) -> None:
        evidence_path = self.root / "disappeared-run"
        evidence_path.mkdir()
        evidence_file = evidence_path / "task.json"
        evidence_file.write_bytes(b'{"task":"fixture"}\n')

        def remove_evidence_directory() -> str:
            evidence_file.unlink()
            evidence_path.rmdir()
            return "2026-07-23T00:00:00.000000Z"

        with patch(
            "seal_legacy.run_manifest._utc_timestamp",
            side_effect=remove_evidence_directory,
        ):
            with self.assertRaisesRegex(
                RunManifestError,
                r"Could not write run-manifest\.json",
            ):
                create_run_manifest(
                    evidence_path,
                    task_id="TASK-MANIFEST",
                    run_id="run-disappeared",
                    evidence_files=(PurePosixPath("task.json"),),
                )

        self.assertFalse(evidence_path.exists())

    def test_manifest_contains_sorted_raw_byte_records_and_excludes_consumers(self) -> None:
        self._create_task(
            checks=[
                self._check("first", "print('first')"),
                self._check("second", "print('second')"),
            ]
        )
        self._write("src/example.txt", "after\n")
        run = self._run()
        manifest_path = self._manifest_path(run.evidence_path)
        manifest = self._document(manifest_path)

        paths = [record["path"] for record in manifest["files"]]
        self.assertEqual(paths, sorted(paths))
        self.assertEqual(paths, sorted(run.verification["evidence_files"]))
        self.assertNotIn(RUN_MANIFEST_FILENAME, paths)
        self.assertNotIn("verdict.raw.json", paths)
        self.assertNotIn("verdict.json", paths)
        self.assertNotIn("completion.json", paths)
        for record in manifest["files"]:
            contents = (run.evidence_path / record["path"]).read_bytes()
            self.assertEqual(record["size_bytes"], len(contents))
            self.assertEqual(record["sha256"], hashlib.sha256(contents).hexdigest())

        digest_payload = {
            "schema_version": 1,
            "task_id": "TASK-MANIFEST",
            "run_id": run.run_id,
            "files": manifest["files"],
        }
        canonical = json.dumps(
            digest_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        self.assertEqual(manifest["evidence_sha256"], hashlib.sha256(canonical).hexdigest())
        self.assertEqual(
            validate_run("TASK-MANIFEST", run.run_id, cwd=self.repository).evidence_sha256,
            manifest["evidence_sha256"],
        )

        record_verdict(
            "TASK-MANIFEST",
            run.run_id,
            self._verdict_file("TASK-MANIFEST", run.run_id),
            cwd=self.repository,
        )
        complete_task("TASK-MANIFEST", run.run_id, cwd=self.repository)
        self.assertEqual(self._document(manifest_path), manifest)

    def test_detects_raw_byte_tampering_for_every_mechanical_file(self) -> None:
        run = self._valid_run()
        checks = self._document(run.evidence_path / "checks.json")
        log_paths = [
            checks["checks"][0]["stdout_path"],
            checks["checks"][0]["stderr_path"],
        ]
        paths = [
            "task.json",
            "changed-files.json",
            "diff.patch",
            "checks.json",
            "source-before-checks.json",
            "source-after-checks.json",
            "verification.json",
            *log_paths,
        ]

        for relative_path in paths:
            with self.subTest(relative_path=relative_path):
                path = run.evidence_path / relative_path
                original = path.read_bytes()
                path.write_bytes(b" " + original)
                try:
                    with self.assertRaisesRegex(RunValidationError, r"run-manifest\.json"):
                        validate_run("TASK-MANIFEST", run.run_id, cwd=self.repository)
                finally:
                    path.write_bytes(original)

    def test_rejects_missing_files_and_unsafe_manifest_records(self) -> None:
        run = self._valid_run()
        task_path = run.evidence_path / "task.json"
        task_bytes = task_path.read_bytes()
        task_path.unlink()
        with self.assertRaises(RunValidationError):
            validate_run("TASK-MANIFEST", run.run_id, cwd=self.repository)
        task_path.write_bytes(task_bytes)

        checks = self._document(run.evidence_path / "checks.json")
        log_path = run.evidence_path / checks["checks"][0]["stdout_path"]
        log_bytes = log_path.read_bytes()
        log_path.unlink()
        with self.assertRaises(RunValidationError):
            validate_run("TASK-MANIFEST", run.run_id, cwd=self.repository)
        log_path.write_bytes(log_bytes)

        manifest_path = self._manifest_path(run.evidence_path)
        original = self._document(manifest_path)
        mutations = {
            "missing-record": lambda value: value.__setitem__(
                "files", [record for record in value["files"] if record["path"] != "diff.patch"]
            ),
            "unknown-record": lambda value: value["files"].append(
                {"path": "unknown.bin", "size_bytes": 0, "sha256": "0" * 64}
            ),
            "duplicate-record": lambda value: value["files"].append(
                copy.deepcopy(value["files"][0])
            ),
            "traversal": lambda value: value["files"][0].__setitem__("path", "../outside"),
            "absolute": lambda value: value["files"][0].__setitem__("path", "/tmp/outside"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                document = copy.deepcopy(original)
                mutate(document)
                self._write_document(manifest_path, document)
                with self.assertRaises(RunValidationError):
                    validate_run("TASK-MANIFEST", run.run_id, cwd=self.repository)
        self._write_document(manifest_path, original)

        if os.name == "posix":
            outside = self.root / "outside.stdout"
            outside.write_text("outside\n", encoding="utf-8")
            log_path.unlink()
            log_path.symlink_to(outside)
            with self.assertRaises(RunValidationError):
                validate_run("TASK-MANIFEST", run.run_id, cwd=self.repository)

    def test_rejects_manifest_identity_hash_and_structure_tampering(self) -> None:
        run = self._valid_run()
        manifest_path = self._manifest_path(run.evidence_path)
        original = self._document(manifest_path)
        mutations = {
            "task-id": lambda value: value.__setitem__("task_id", "TASK-OTHER"),
            "run-id": lambda value: value.__setitem__("run_id", "other-run"),
            "size": lambda value: value["files"][0].__setitem__("size_bytes", 1),
            "file-hash": lambda value: value["files"][0].__setitem__("sha256", "0" * 64),
            "digest": lambda value: value.__setitem__("evidence_sha256", "0" * 64),
            "schema-version": lambda value: value.__setitem__("schema_version", 2),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                document = copy.deepcopy(original)
                mutate(document)
                self._write_document(manifest_path, document)
                with self.assertRaises(RunValidationError):
                    validate_run("TASK-MANIFEST", run.run_id, cwd=self.repository)
        self._write_document(manifest_path, "{")
        with self.assertRaises(RunValidationError):
            validate_run("TASK-MANIFEST", run.run_id, cwd=self.repository)

    def test_missing_manifest_is_explicitly_incomplete_evidence(self) -> None:
        run = self._valid_run()
        self._manifest_path(run.evidence_path).unlink()

        with self.assertRaisesRegex(RunValidationError, r"run-manifest\.json is missing"):
            validate_run("TASK-MANIFEST", run.run_id, cwd=self.repository)

    def test_failed_timeout_and_scope_runs_remain_valid_when_manifest_matches(self) -> None:
        self._create_task(
            task_id="TASK-FAILED",
            checks=[self._check("failed", "import sys; sys.exit(3)")],
        )
        self._write("src/example.txt", "failed\n")
        failed_run = self._run("TASK-FAILED")
        self.assertEqual(
            validate_run("TASK-FAILED", failed_run.run_id, cwd=self.repository).mechanical_result,
            "fail",
        )

        self._create_task(
            task_id="TASK-TIMEOUT",
            checks=[
                self._check(
                    "timeout", "import sys; sys.exit(24)", timeout_seconds=1
                )
            ],
        )
        timeout_run = self._run("TASK-TIMEOUT")
        rewrite_failed_check_as_timeout(
            timeout_run.evidence_path,
            task_id="TASK-TIMEOUT",
            run_id=timeout_run.run_id,
        )
        self.assertTrue(
            validate_run("TASK-TIMEOUT", timeout_run.run_id, cwd=self.repository)
            .check_records[0]["timed_out"]
        )

        self._create_task(task_id="TASK-SCOPE")
        self._write("docs/outside.txt", "outside scope\n")
        scope_run = self._run("TASK-SCOPE")
        self.assertFalse(
            validate_run("TASK-SCOPE", scope_run.run_id, cwd=self.repository).scope_pass
        )

    def test_consumers_use_validated_digest_and_do_not_recover_mismatches(self) -> None:
        run = self._valid_run()
        validated = validate_run("TASK-MANIFEST", run.run_id, cwd=self.repository)
        bundle = create_verification_bundle(
            "TASK-MANIFEST", run.run_id, self.root / "bundle", cwd=self.repository
        )
        self.assertEqual(bundle.manifest["source_evidence_sha256"], validated.evidence_sha256)

        completion = complete_task("TASK-MANIFEST", run.run_id, cwd=self.repository)
        self.assertEqual(completion.completion["evidence_sha256"], validated.evidence_sha256)

        record_verdict(
            "TASK-MANIFEST",
            run.run_id,
            self._verdict_file("TASK-MANIFEST", run.run_id),
            cwd=self.repository,
        )
        diff_path = run.evidence_path / "diff.patch"
        original = diff_path.read_bytes()
        tampered = original + b"\nno-automatic-recovery"
        diff_path.write_bytes(tampered)

        with self.assertRaises(BundleEvidenceError):
            create_verification_bundle(
                "TASK-MANIFEST",
                run.run_id,
                self.root / "rejected-bundle",
                cwd=self.repository,
            )
        with self.assertRaises(CompletionEvidenceError):
            complete_task("TASK-MANIFEST", run.run_id, cwd=self.repository)
        with self.assertRaises(VerdictEvidenceError):
            record_verdict(
                "TASK-MANIFEST",
                run.run_id,
                self._verdict_file("TASK-MANIFEST", run.run_id),
                cwd=self.repository,
            )
        with self.assertRaises(VerdictEvidenceError):
            show_verdict("TASK-MANIFEST", run.run_id, cwd=self.repository)

        self.assertEqual(diff_path.read_bytes(), tampered)
        self.assertFalse((self.root / "rejected-bundle").exists())
