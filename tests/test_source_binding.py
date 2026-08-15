"""End-to-end regression coverage for source-bound Evidence Runs.

These tests deliberately use disposable Git repositories and public Seal Legacy
entry points.  They protect the contract between verification-time snapshots,
stored Run validation, portable bundles, and completion-time source binding.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from typing import Any
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from seal_legacy.bundle import create_verification_bundle
import seal_legacy.evidence as evidence_module
from seal_legacy.evidence import (
    CompletionError,
    EvidenceRepositoryError,
    complete_task,
    verify_task,
)
from seal_legacy.run_manifest import create_run_manifest
from seal_legacy.run_validator import RunValidationError, validate_run
from seal_legacy.task import create_task
from tests._evidence_fixtures import rewrite_failed_check_as_timeout


SOURCE_BEFORE_CHECKS = "source-before-checks.json"
SOURCE_AFTER_CHECKS = "source-after-checks.json"
SOURCE_BINDING_FIELDS = {
    "source_snapshot_schema_version",
    "source_before_checks_sha256",
    "source_after_checks_sha256",
    "source_stable_during_checks",
}
SOURCE_MISMATCH_EXIT_CODE = 9


class SourceBindingIntegrationTests(unittest.TestCase):
    """Exercise v2 source binding without relying on the Seal Legacy repository."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.repository_index = 0
        self.task_source_index = 0

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _new_repository(self) -> Path:
        self.repository_index += 1
        repository = self.root / f"repository-{self.repository_index}"
        repository.mkdir()
        self._git(repository, "init", "--quiet")
        self._write(repository, ".gitignore", "ignored/\n")
        self._write(repository, ".seal/checks.json", '{"checks": []}\n')
        self._write(repository, "src/example.txt", "baseline\n")
        self._write(repository, "src/delete.txt", "delete baseline\n")
        self._write(repository, "src/rename.txt", "rename baseline\n")
        self._write(repository, "src/mode.txt", "mode baseline\n")
        self._write(repository, "src/required.txt", "required baseline\n")
        self._write(repository, "src/optional.txt", "optional baseline\n")
        self._write(repository, "src/binary.bin", b"\x00binary baseline\xff")
        self._git(repository, "add", ".")
        self._commit(repository, "fixture")
        return repository

    def _create_task(
        self,
        repository: Path,
        *,
        checks: list[dict[str, object]] | None = None,
        verifier_required: bool = False,
        scope: list[str] | None = None,
    ) -> str:
        task_id = "TASK-SOURCE-BINDING"
        specification = {
            "schema_version": 1,
            "id": task_id,
            "type": "test",
            "objective": "Exercise source-bound verification and completion.",
            "scope": ["src"] if scope is None else scope,
            "checks": checks
            if checks is not None
            else [self._python_check("pass", "print('ok')")],
            "risk": "high",
            "verifier": {"required": verifier_required},
        }
        self.task_source_index += 1
        source = self.root / f"task-{self.task_source_index}.json"
        source.write_text(json.dumps(specification), encoding="utf-8")
        create_task(source, cwd=repository)
        return task_id

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

    @staticmethod
    def _git(repository: Path, *arguments: str) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def _commit(self, repository: Path, message: str) -> None:
        self._git(
            repository,
            "-c",
            "user.name=Seal Legacy Test",
            "-c",
            "user.email=seal-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            message,
        )

    @staticmethod
    def _write(repository: Path, relative_path: str, contents: str | bytes) -> None:
        path = repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contents, bytes):
            path.write_bytes(contents)
        else:
            path.write_text(contents, encoding="utf-8")

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, document: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _run_cli(
        self,
        repository: Path,
        *arguments: str,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(SOURCE_ROOT)
        if existing_pythonpath:
            environment["PYTHONPATH"] += os.pathsep + existing_pythonpath
        return subprocess.run(
            [sys.executable, "-m", "seal_legacy", *arguments],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def _complete(
        self,
        repository: Path,
        task_id: str,
        run_id: str,
    ) -> subprocess.CompletedProcess[str]:
        return self._run_cli(
            repository,
            "complete",
            task_id,
            "--run-id",
            run_id,
        )

    def _completion_error_code(
        self,
        repository: Path,
        task_id: str,
        run_id: str,
    ) -> int:
        try:
            complete_task(task_id, run_id, cwd=repository)
        except CompletionError as error:
            return int(error.exit_code)
        self.fail("Completion unexpectedly succeeded.")

    @staticmethod
    def _snapshot_digest(document: dict[str, Any]) -> str:
        payload = {
            "schema_version": document["schema_version"],
            "baseline": document["baseline"],
            "entries": document["entries"],
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
        ).hexdigest()

    def _refresh_manifest(
        self,
        task_id: str,
        run_id: str,
        evidence_path: Path,
    ) -> None:
        verification = self._read_json(evidence_path / "verification.json")
        create_run_manifest(
            evidence_path,
            task_id=task_id,
            run_id=run_id,
            evidence_files=tuple(
                PurePosixPath(path)
                for path in verification["evidence_files"]
            ),
        )

    @staticmethod
    def _snapshot_entries(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {entry["path"]: entry for entry in document["entries"]}

    def test_verify_writes_source_bound_evidence_v2_and_validates_it(self) -> None:
        repository = self._new_repository()
        task_id = self._create_task(repository)
        self._write(repository, "src/example.txt", "candidate\n")

        run = verify_task(task_id, cwd=repository)

        before_path = run.evidence_path / SOURCE_BEFORE_CHECKS
        after_path = run.evidence_path / SOURCE_AFTER_CHECKS
        before = self._read_json(before_path)
        after = self._read_json(after_path)
        self.assertEqual(before, after)
        self.assertEqual(before["schema_version"], 1)
        self.assertEqual(
            before["baseline"],
            self._git(repository, "rev-parse", "HEAD"),
        )
        self.assertIn("src/example.txt", self._snapshot_entries(before))

        verification = run.verification
        self.assertEqual(verification["schema_version"], 2)
        self.assertEqual(verification["source_snapshot_schema_version"], 1)
        self.assertEqual(
            verification["source_before_checks_sha256"],
            before["snapshot_sha256"],
        )
        self.assertEqual(
            verification["source_after_checks_sha256"],
            after["snapshot_sha256"],
        )
        self.assertTrue(verification["source_stable_during_checks"])
        self.assertEqual(verification["mechanical_result"], "pass")
        self.assertTrue(
            {SOURCE_BEFORE_CHECKS, SOURCE_AFTER_CHECKS}
            <= set(verification["evidence_files"])
        )

        manifest = self._read_json(run.evidence_path / "run-manifest.json")
        manifested_paths = {record["path"] for record in manifest["files"]}
        self.assertTrue(
            {SOURCE_BEFORE_CHECKS, SOURCE_AFTER_CHECKS} <= manifested_paths
        )

        validated = validate_run(task_id, run.run_id, cwd=repository)
        self.assertTrue(validated.source_stable_during_checks)
        self.assertEqual(
            validated.source_before_checks.to_document(),
            before,
        )
        self.assertEqual(
            validated.source_after_checks.to_document(),
            after,
        )

    def test_unicode_space_binary_and_mode_survive_v2_end_to_end(self) -> None:
        repository = self._new_repository()
        task_id = self._create_task(repository)
        special_path = "src/한글 binary name.bin"
        contents = b"\x00candidate\xff\n"
        self._write(repository, special_path, contents)
        if os.name == "posix":
            os.chmod(repository / "src/mode.txt", 0o755)

        run = verify_task(task_id, cwd=repository)
        validated = validate_run(task_id, run.run_id, cwd=repository)
        entries = {
            entry.path: entry
            for entry in validated.source_after_checks.entries
        }

        self.assertEqual(
            entries[special_path].sha256,
            hashlib.sha256(contents).hexdigest(),
        )
        if os.name == "posix":
            self.assertEqual(entries["src/mode.txt"].mode, "100755")
        bundle = create_verification_bundle(
            task_id,
            run.run_id,
            self.root / "special-path-bundle",
            cwd=repository,
        )
        self.assertTrue(bundle.bundle_path.is_dir())
        completion = self._complete(repository, task_id, run.run_id)
        self.assertEqual(completion.returncode, 0, completion.stderr)

    def test_product_mutations_during_checks_make_v2_run_unstable(self) -> None:
        repository = self._new_repository()
        checks = [
            self._python_check(
                "tracked",
                "from pathlib import Path; "
                "Path('src/example.txt').write_text('during check\\n', encoding='utf-8')",
            ),
            self._python_check(
                "untracked",
                "from pathlib import Path; "
                "Path('src/untracked.txt').write_text('new\\n', encoding='utf-8')",
            ),
            self._python_check(
                "binary",
                "from pathlib import Path; "
                "Path('src/binary.bin').write_bytes(b'\\x00during-check\\xff')",
            ),
            self._python_check(
                "delete",
                "from pathlib import Path; Path('src/delete.txt').unlink()",
            ),
            self._python_check(
                "rename",
                "from pathlib import Path; "
                "Path('src/rename.txt').rename('src/renamed.txt'); "
                "Path('src/renamed.txt').write_text('renamed and changed\\n', encoding='utf-8')",
            ),
            self._python_check(
                "optional-failure",
                "from pathlib import Path; import sys; "
                "Path('src/optional.txt').write_text('optional\\n', encoding='utf-8'); "
                "sys.exit(24)",
                required=False,
            ),
            self._python_check(
                "required-failure",
                "from pathlib import Path; import sys; "
                "Path('src/required.txt').write_text('failed\\n', encoding='utf-8'); "
                "sys.exit(23)",
            ),
            self._python_check(
                "timeout",
                "from pathlib import Path; import time; "
                "Path('src/timeout.txt').write_text('timeout\\n', encoding='utf-8'); "
                "time.sleep(30)",
                timeout_seconds=1,
            ),
        ]
        if os.name == "posix":
            checks.append(
                self._python_check(
                    "mode",
                    "import os; os.chmod('src/mode.txt', 0o755)",
                )
            )

        task_id = self._create_task(
            repository,
            checks=checks,
        )
        run = verify_task(task_id, cwd=repository)
        after = self._read_json(
            run.evidence_path / SOURCE_AFTER_CHECKS
        )
        entries = self._snapshot_entries(after)
        check_records = {
            record["name"]: record
            for record in self._read_json(
                run.evidence_path / "checks.json"
            )["checks"]
        }

        self.assertFalse(run.verification["source_stable_during_checks"])
        self.assertFalse(run.verification["required_checks_pass"])
        self.assertEqual(run.verification["mechanical_result"], "fail")
        self.assertEqual(entries["src/delete.txt"]["state"], "deleted")
        self.assertEqual(entries["src/rename.txt"]["state"], "deleted")
        for path in (
            "src/example.txt",
            "src/untracked.txt",
            "src/binary.bin",
            "src/renamed.txt",
            "src/optional.txt",
            "src/required.txt",
            "src/timeout.txt",
        ):
            self.assertEqual(entries[path]["state"], "present")
        if os.name == "posix":
            self.assertEqual(entries["src/mode.txt"]["mode"], "100755")
        self.assertFalse(check_records["required-failure"]["passed"])
        self.assertTrue(check_records["required-failure"]["required"])
        self.assertFalse(check_records["optional-failure"]["passed"])
        self.assertFalse(check_records["optional-failure"]["required"])
        self.assertTrue(check_records["timeout"]["timed_out"])
        self.assertTrue(check_records["timeout"]["required"])

        before = self._read_json(
            run.evidence_path / SOURCE_BEFORE_CHECKS
        )
        self.assertNotEqual(
            before["snapshot_sha256"],
            after["snapshot_sha256"],
        )

    def test_ignored_and_seal_metadata_mutations_do_not_change_source(self) -> None:
        repository = self._new_repository()
        program = (
            "from pathlib import Path; "
            "Path('ignored').mkdir(exist_ok=True); "
            "Path('ignored/generated.txt').write_text('ignored\\n', encoding='utf-8'); "
            "Path('.seal/lessons.md').write_text('metadata\\n', encoding='utf-8')"
        )
        task_id = self._create_task(
            repository,
            checks=[self._python_check("metadata", program)],
        )

        run = verify_task(task_id, cwd=repository)

        before = self._read_json(run.evidence_path / SOURCE_BEFORE_CHECKS)
        after = self._read_json(run.evidence_path / SOURCE_AFTER_CHECKS)
        self.assertEqual(before, after)
        self.assertEqual(before["entries"], [])
        self.assertTrue(run.verification["source_stable_during_checks"])
        self.assertEqual(run.verification["mechanical_result"], "pass")

    def test_s0_failure_prevents_checks_and_run_allocation(self) -> None:
        repository = self._new_repository()
        marker = repository / "check-ran.txt"
        task_id = self._create_task(
            repository,
            checks=[
                self._python_check(
                    "must-not-run",
                    "from pathlib import Path; "
                    "Path('check-ran.txt').write_text('ran', encoding='utf-8')",
                )
            ],
        )
        task_path = (
            repository / ".seal" / "tasks" / f"{task_id}.json"
        )
        task = self._read_json(task_path)
        task["baseline"] = "refs/heads/missing-baseline"
        self._write_json(task_path, task)

        with self.assertRaises(EvidenceRepositoryError):
            verify_task(task_id, cwd=repository)

        self.assertFalse(marker.exists())
        self.assertFalse(
            (repository / ".seal" / "evidence" / task_id).exists()
        )

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires FIFO support")
    def test_s1_failure_preserves_incomplete_run_without_success_stdout(self) -> None:
        repository = self._new_repository()
        task_id = self._create_task(
            repository,
            checks=[
                self._python_check(
                    "create-fifo",
                    "import os; os.mkfifo('src/check-created.fifo')",
                )
            ],
        )

        result = self._run_cli(repository, "verify", task_id)

        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(result.stdout, "")
        evidence_root = repository / ".seal" / "evidence" / task_id
        run_directories = [path for path in evidence_root.iterdir() if path.is_dir()]
        self.assertEqual(len(run_directories), 1)
        incomplete = run_directories[0]
        self.assertTrue((incomplete / "task.json").is_file())
        self.assertTrue(any((incomplete / "checks").iterdir()))
        self.assertFalse((incomplete / "verification.json").exists())
        self.assertFalse((incomplete / "run-manifest.json").exists())

    def test_snapshot_persistence_failure_leaves_an_incomplete_run(self) -> None:
        repository = self._new_repository()
        task_id = self._create_task(repository)
        real_atomic_write_json = evidence_module.atomic_write_json

        def fail_source_after(path: Path, document: object) -> None:
            if Path(path).name == SOURCE_AFTER_CHECKS:
                raise OSError("simulated snapshot write failure")
            real_atomic_write_json(path, document)

        with mock.patch.object(
            evidence_module,
            "atomic_write_json",
            side_effect=fail_source_after,
        ):
            with self.assertRaises(EvidenceRepositoryError):
                verify_task(task_id, cwd=repository)

        evidence_root = repository / ".seal" / "evidence" / task_id
        run_directories = [path for path in evidence_root.iterdir() if path.is_dir()]
        self.assertEqual(len(run_directories), 1)
        incomplete = run_directories[0]
        self.assertTrue((incomplete / "task.json").is_file())
        self.assertTrue((incomplete / SOURCE_BEFORE_CHECKS).is_file())
        self.assertFalse((incomplete / SOURCE_AFTER_CHECKS).exists())
        self.assertFalse((incomplete / "verification.json").exists())
        self.assertFalse((incomplete / "run-manifest.json").exists())

    def test_post_verify_product_changes_return_source_mismatch(self) -> None:
        repository = self._new_repository()
        task_id = self._create_task(repository)
        run = verify_task(task_id, cwd=repository)
        cases = ["text", "binary", "untracked", "delete", "rename"]
        if os.name == "posix":
            cases.append("mode")

        for mutation in cases:
            with self.subTest(mutation=mutation):
                if mutation == "text":
                    self._write(repository, "src/example.txt", "stale\n")
                elif mutation == "binary":
                    self._write(repository, "src/example.txt", b"\x00stale\xff")
                elif mutation == "untracked":
                    self._write(repository, "src/new.txt", "stale\n")
                elif mutation == "delete":
                    (repository / "src/delete.txt").unlink()
                elif mutation == "rename":
                    (repository / "src/rename.txt").rename(
                        repository / "src/renamed.txt"
                    )
                else:
                    os.chmod(repository / "src/mode.txt", 0o755)

                self.assertEqual(
                    self._completion_error_code(
                        repository,
                        task_id,
                        run.run_id,
                    ),
                    SOURCE_MISMATCH_EXIT_CODE,
                )
                self.assertFalse(
                    (run.evidence_path / "completion.json").exists()
                )
                if mutation in {"text", "binary"}:
                    self._write(repository, "src/example.txt", "baseline\n")
                elif mutation == "untracked":
                    (repository / "src/new.txt").unlink()
                elif mutation == "delete":
                    self._write(
                        repository,
                        "src/delete.txt",
                        "delete baseline\n",
                    )
                elif mutation == "rename":
                    (repository / "src/renamed.txt").rename(
                        repository / "src/rename.txt"
                    )
                else:
                    os.chmod(repository / "src/mode.txt", 0o644)

        restored = complete_task(task_id, run.run_id, cwd=repository)
        self.assertTrue(restored.completion_path.is_file())

    @unittest.skipUnless(os.name == "posix", "executable mode requires POSIX")
    def test_owner_execute_removal_returns_source_mismatch(self) -> None:
        repository = self._new_repository()
        path = repository / "src/mode.txt"
        path.chmod(stat.S_IMODE(path.stat().st_mode) | 0o111)
        if not path.stat().st_mode & stat.S_IXUSR:
            self.skipTest("filesystem does not preserve executable mode")
        self._git(
            repository,
            "update-index",
            "--chmod=+x",
            "--",
            "src/mode.txt",
        )
        self._commit(repository, "executable baseline")
        task_id = self._create_task(repository)
        run = verify_task(task_id, cwd=repository)

        path.chmod(
            (stat.S_IMODE(path.stat().st_mode) | stat.S_IXGRP | stat.S_IXOTH)
            & ~stat.S_IXUSR
        )
        current_mode = path.stat().st_mode
        self.assertFalse(current_mode & stat.S_IXUSR)
        self.assertTrue(current_mode & stat.S_IXGRP)
        self.assertTrue(current_mode & stat.S_IXOTH)
        result = self._complete(repository, task_id, run.run_id)

        self.assertEqual(result.returncode, SOURCE_MISMATCH_EXIT_CODE, result.stderr)
        self.assertFalse((run.evidence_path / "completion.json").exists())

    def test_exit_9_preserves_an_existing_successful_completion_record(self) -> None:
        repository = self._new_repository()
        task_id = self._create_task(repository)
        run = verify_task(task_id, cwd=repository)
        first = self._complete(repository, task_id, run.run_id)
        self.assertEqual(first.returncode, 0, first.stderr)
        completion_path = run.evidence_path / "completion.json"
        original_completion = completion_path.read_bytes()
        self._write(repository, "src/example.txt", "stale after completion\n")

        second = self._complete(repository, task_id, run.run_id)

        self.assertEqual(
            second.returncode,
            SOURCE_MISMATCH_EXIT_CODE,
            second.stderr,
        )
        self.assertEqual(completion_path.read_bytes(), original_completion)

    def test_restored_final_source_completes_across_git_layers(self) -> None:
        repository = self._new_repository()
        task_id = self._create_task(repository)
        self._write(repository, "src/example.txt", "verified candidate\n")
        run = verify_task(task_id, cwd=repository)
        self._write(repository, "src/example.txt", "temporary stale value\n")
        self._write(repository, "src/example.txt", "verified candidate\n")

        for final_layer in ("unstaged", "staged", "committed"):
            with self.subTest(final_layer=final_layer):
                if final_layer in {"staged", "committed"}:
                    self._git(repository, "add", "src/example.txt")
                if final_layer == "committed":
                    self._commit(repository, "commit verified source")

                completion = complete_task(
                    task_id,
                    run.run_id,
                    cwd=repository,
                )

                self.assertTrue(completion.completion_path.is_file())

    def test_v1_style_run_is_unsupported_for_all_consumers(self) -> None:
        repository = self._new_repository()
        task_id = self._create_task(repository)
        run = verify_task(task_id, cwd=repository)
        verification_path = run.evidence_path / "verification.json"
        verification = self._read_json(verification_path)
        verification["schema_version"] = 1
        for field in SOURCE_BINDING_FIELDS:
            verification.pop(field)
        verification["evidence_files"] = [
            path
            for path in verification["evidence_files"]
            if path not in {SOURCE_BEFORE_CHECKS, SOURCE_AFTER_CHECKS}
        ]
        verification["mechanical_result"] = (
            "pass"
            if verification["scope_pass"]
            and verification["required_checks_pass"]
            else "fail"
        )
        verification_path.write_text(
            json.dumps(verification, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (run.evidence_path / SOURCE_BEFORE_CHECKS).unlink()
        (run.evidence_path / SOURCE_AFTER_CHECKS).unlink()
        create_run_manifest(
            run.evidence_path,
            task_id=task_id,
            run_id=run.run_id,
            evidence_files=tuple(
                PurePosixPath(path) for path in verification["evidence_files"]
            ),
        )

        with self.assertRaisesRegex(
            RunValidationError,
            "unsupported schema_version",
        ):
            validate_run(task_id, run.run_id, cwd=repository)

        verdict_source = self.root / "verdict.json"
        verdict_source.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "task_id": task_id,
                    "run_id": run.run_id,
                    "verifier": {
                        "kind": "manual",
                        "runner": "test-reviewer",
                        "model": None,
                        "fresh_context": True,
                    },
                    "verdict": "pass",
                    "summary": "Valid input that must not bypass Run validation.",
                    "findings": [],
                    "reviewed_at": "2026-07-23T00:00:00Z",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        commands = (
            (
                "verifier",
                "bundle",
                task_id,
                "--run-id",
                run.run_id,
                "--output",
                str(self.root / "unsupported-bundle"),
            ),
            (
                "verifier",
                "record",
                task_id,
                "--run-id",
                run.run_id,
                "--file",
                str(verdict_source),
            ),
            (
                "verifier",
                "show",
                task_id,
                "--run-id",
                run.run_id,
            ),
            (
                "complete",
                task_id,
                "--run-id",
                run.run_id,
            ),
        )
        for command in commands:
            with self.subTest(command=command[:2]):
                result = self._run_cli(repository, *command)
                self.assertEqual(result.returncode, 8, result.stderr)
                self.assertIn("unsupported schema_version", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_bundle_packages_recorded_snapshots_without_current_source_gate(self) -> None:
        repository = self._new_repository()
        task_id = self._create_task(repository)
        self._write(repository, "src/example.txt", "verified candidate\n")
        run = verify_task(task_id, cwd=repository)
        self._write(repository, "src/example.txt", "changed after verify\n")
        output = self.root / "bundle"

        bundle = create_verification_bundle(
            task_id,
            run.run_id,
            output,
            cwd=repository,
        )

        bundled_paths = {record["path"] for record in bundle.manifest["files"]}
        self.assertTrue(
            {SOURCE_BEFORE_CHECKS, SOURCE_AFTER_CHECKS} <= bundled_paths
        )
        self.assertEqual(
            self._read_json(output / SOURCE_BEFORE_CHECKS),
            self._read_json(run.evidence_path / SOURCE_BEFORE_CHECKS),
        )
        self.assertEqual(
            self._read_json(output / SOURCE_AFTER_CHECKS),
            self._read_json(run.evidence_path / SOURCE_AFTER_CHECKS),
        )
        completion = self._complete(repository, task_id, run.run_id)
        self.assertEqual(
            completion.returncode,
            SOURCE_MISMATCH_EXIT_CODE,
            completion.stderr,
        )

    def test_corrupt_source_evidence_precedes_current_source_mismatch(self) -> None:
        repository = self._new_repository()
        task_id = self._create_task(repository)
        run = verify_task(task_id, cwd=repository)
        self._write(repository, "src/example.txt", "stale\n")
        (run.evidence_path / SOURCE_AFTER_CHECKS).write_text(
            "{",
            encoding="utf-8",
        )

        result = self._complete(repository, task_id, run.run_id)

        self.assertEqual(result.returncode, 8, result.stderr)
        self.assertFalse((run.evidence_path / "completion.json").exists())

    def test_corrupt_verdict_precedes_current_source_mismatch(self) -> None:
        repository = self._new_repository()
        task_id = self._create_task(repository)
        run = verify_task(task_id, cwd=repository)
        self._write(repository, "src/example.txt", "stale\n")
        (run.evidence_path / "verdict.raw.json").write_text(
            "{",
            encoding="utf-8",
        )

        result = self._complete(repository, task_id, run.run_id)

        self.assertEqual(result.returncode, 8, result.stderr)
        self.assertFalse((run.evidence_path / "completion.json").exists())

    def test_source_binding_integrity_tampering_returns_exit_8(self) -> None:
        repository = self._new_repository()
        task_id = self._create_task(repository)
        self._write(repository, "src/example.txt", "candidate\n")
        self._write(repository, "src/second.txt", "second\n")
        run = verify_task(task_id, cwd=repository)
        before_path = run.evidence_path / SOURCE_BEFORE_CHECKS
        after_path = run.evidence_path / SOURCE_AFTER_CHECKS
        verification_path = run.evidence_path / "verification.json"
        manifest_path = run.evidence_path / "run-manifest.json"
        pristine_documents = {
            path: path.read_bytes()
            for path in (
                before_path,
                after_path,
                verification_path,
                manifest_path,
            )
        }
        cases = (
            "missing-before",
            "missing-after",
            "malformed-after",
            "verification-digest",
            "entry",
            "entry-mode-type",
            "baseline",
            "stability",
            "aggregate",
            "ordering",
            "manifest",
        )
        for case in cases:
            with self.subTest(case=case):
                for path, contents in pristine_documents.items():
                    path.write_bytes(contents)

                refresh_manifest = True
                if case == "missing-before":
                    before_path.unlink()
                    refresh_manifest = False
                elif case == "missing-after":
                    after_path.unlink()
                    refresh_manifest = False
                elif case == "malformed-after":
                    after_path.write_text("{", encoding="utf-8")
                elif case == "verification-digest":
                    verification = self._read_json(verification_path)
                    verification["source_after_checks_sha256"] = "0" * 64
                    self._write_json(verification_path, verification)
                elif case == "entry":
                    after = self._read_json(after_path)
                    after["entries"][0]["size_bytes"] += 1
                    self._write_json(after_path, after)
                elif case == "entry-mode-type":
                    after = self._read_json(after_path)
                    after["entries"][0]["mode"] = []
                    self._write_json(after_path, after)
                elif case == "baseline":
                    after = self._read_json(after_path)
                    after["baseline"] = "3" * 40
                    after["snapshot_sha256"] = self._snapshot_digest(after)
                    self._write_json(after_path, after)
                elif case == "stability":
                    verification = self._read_json(verification_path)
                    verification["source_stable_during_checks"] = False
                    self._write_json(verification_path, verification)
                elif case == "aggregate":
                    verification = self._read_json(verification_path)
                    verification["mechanical_result"] = "fail"
                    self._write_json(verification_path, verification)
                elif case == "ordering":
                    after = self._read_json(after_path)
                    after["entries"].reverse()
                    after["snapshot_sha256"] = self._snapshot_digest(after)
                    self._write_json(after_path, after)
                else:
                    manifest = self._read_json(manifest_path)
                    manifest["evidence_sha256"] = "0" * 64
                    self._write_json(manifest_path, manifest)
                    refresh_manifest = False

                if refresh_manifest:
                    self._refresh_manifest(
                        task_id,
                        run.run_id,
                        run.evidence_path,
                    )

                self.assertEqual(
                    self._completion_error_code(
                        repository,
                        task_id,
                        run.run_id,
                    ),
                    8,
                )
                self.assertFalse(
                    (run.evidence_path / "completion.json").exists()
                )

    def test_stale_source_precedes_verifier_and_check_failures(self) -> None:
        repository = self._new_repository()
        task_id = self._create_task(
            repository,
            checks=[
                self._python_check(
                    "failure",
                    "import sys; sys.exit(31)",
                )
            ],
            verifier_required=True,
        )
        run = verify_task(task_id, cwd=repository)
        self._write(repository, "src/example.txt", "stale\n")

        result = self._complete(repository, task_id, run.run_id)

        self.assertEqual(
            result.returncode,
            SOURCE_MISMATCH_EXIT_CODE,
            result.stderr,
        )
        self.assertFalse((run.evidence_path / "completion.json").exists())

    def test_check_time_source_instability_precedes_completion_policy(self) -> None:
        repository = self._new_repository()
        program = (
            "from pathlib import Path; import sys; "
            "Path('src/example.txt').write_text('during check\\n', encoding='utf-8'); "
            "sys.exit(32)"
        )
        task_id = self._create_task(
            repository,
            checks=[self._python_check("mutating-failure", program)],
            verifier_required=True,
        )
        run = verify_task(task_id, cwd=repository)

        result = self._complete(repository, task_id, run.run_id)

        self.assertEqual(
            result.returncode,
            SOURCE_MISMATCH_EXIT_CODE,
            result.stderr,
        )
        self.assertFalse((run.evidence_path / "completion.json").exists())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires FIFO support")
    def test_current_source_collection_failure_precedes_source_mismatch(self) -> None:
        repository = self._new_repository()
        task_id = self._create_task(repository)
        run = verify_task(task_id, cwd=repository)
        os.mkfifo(repository / "src/unsupported.fifo")

        result = self._complete(repository, task_id, run.run_id)

        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertFalse((run.evidence_path / "completion.json").exists())

    def test_source_match_preserves_completion_policy_precedence(self) -> None:
        scenarios: list[
            tuple[
                str,
                list[dict[str, object]],
                bool,
                list[str],
                int,
            ]
        ] = [
            (
                "verifier",
                [self._python_check("failure", "import sys; sys.exit(41)")],
                True,
                ["src"],
                7,
            ),
            (
                "scope",
                [
                    self._python_check(
                        "timeout",
                        "import sys; sys.exit(43)",
                        timeout_seconds=1,
                    )
                ],
                False,
                ["docs"],
                4,
            ),
            (
                "timeout",
                [
                    self._python_check(
                        "timeout",
                        "import sys; sys.exit(43)",
                        timeout_seconds=1,
                    )
                ],
                False,
                ["src"],
                6,
            ),
            (
                "required-check",
                [self._python_check("failure", "import sys; sys.exit(42)")],
                False,
                ["src"],
                5,
            ),
        ]

        for name, checks, verifier_required, scope, exit_code in scenarios:
            with self.subTest(name=name):
                repository = self._new_repository()
                task_id = self._create_task(
                    repository,
                    checks=checks,
                    verifier_required=verifier_required,
                    scope=scope,
                )
                if name == "scope":
                    self._write(
                        repository,
                        "src/example.txt",
                        "stable out-of-scope change\n",
                    )
                run = verify_task(task_id, cwd=repository)
                if name in {"scope", "timeout"}:
                    rewrite_failed_check_as_timeout(
                        run.evidence_path,
                        task_id=task_id,
                        run_id=run.run_id,
                    )

                self.assertEqual(
                    self._completion_error_code(
                        repository,
                        task_id,
                        run.run_id,
                    ),
                    exit_code,
                )
                self.assertFalse(
                    (run.evidence_path / "completion.json").exists()
                )
