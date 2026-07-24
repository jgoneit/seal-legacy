"""Integration coverage for portable verifier bundle export."""

from __future__ import annotations

import contextlib
import hashlib
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
from harness.bundle import (
    BundleEvidenceError,
    BundleInputError,
    _path_replacements,
    _path_spellings,
    _pretty_json_bytes,
    _sanitize_text,
    _sanitize_value,
    create_verification_bundle,
)
from harness.evidence import verify_task
from harness.run_validator import validate_run
from harness.task import create_task

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


class VerifierBundleTests(unittest.TestCase):
    """Export a saved Task run without reading arbitrary repository files."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self._git("init", "--quiet")
        self._write(".gitignore", "ignored.txt\n")
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

    def _write(self, relative_path: str, contents: str | bytes) -> None:
        path = self.repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contents, bytes):
            path.write_bytes(contents)
        else:
            path.write_text(contents, encoding="utf-8")

    @staticmethod
    def _python_check(name: str, program: str) -> dict[str, object]:
        return {
            "name": name,
            "argv": [sys.executable, "-c", program],
            "required": True,
        }

    def _create_task(
        self,
        *,
        task_id: str = "TASK-BUNDLE",
        checks: list[dict[str, object]] | None = None,
        objective: str = "Exercise portable verifier bundle export.",
    ) -> None:
        specification = {
            "schema_version": 1,
            "id": task_id,
            "type": "test",
            "objective": objective,
            "scope": ["src"],
            "checks": checks
            if checks is not None
            else [self._python_check("ok", "print('ok')")],
            "risk": "low",
            "verifier": {"required": True},
        }
        source = self.root / f"{task_id}.json"
        source.write_text(json.dumps(specification), encoding="utf-8")
        create_task(source, cwd=self.repository)

    def _run(self, task_id: str = "TASK-BUNDLE"):
        self._write("src/example.txt", "after\n")
        return verify_task(task_id, cwd=self.repository)

    def _bundle(self, run_id: str, *, task_id: str = "TASK-BUNDLE", name: str = "bundle"):
        return create_verification_bundle(
            task_id,
            run_id,
            self.root / name,
            cwd=self.repository,
        )

    def _manifest(self, bundle_path: Path) -> dict[str, object]:
        return json.loads((bundle_path / "manifest.json").read_text(encoding="utf-8"))

    def test_creates_complete_portable_bundle(self) -> None:
        self._create_task()
        run = self._run()

        bundle = self._bundle(run.run_id)

        self.assertEqual(bundle.task_id, "TASK-BUNDLE")
        self.assertEqual(bundle.run_id, run.run_id)
        self.assertTrue(bundle.manifest_path.is_file())
        expected = {
            "task.json",
            "changed-files.json",
            "checks.json",
            "verification.json",
            "diff.patch",
            "source-before-checks.json",
            "source-after-checks.json",
            "verifier.md",
        }
        check_records = json.loads(
            (bundle.bundle_path / "checks.json").read_text(encoding="utf-8")
        )["checks"]
        expected.update(
            path
            for record in check_records
            for path in (record["stdout_path"], record["stderr_path"])
        )
        manifest_paths = {entry["path"] for entry in bundle.manifest["files"]}
        self.assertEqual(manifest_paths, expected)
        self.assertNotIn("manifest.json", manifest_paths)
        self.assertEqual(check_records[0]["cwd"], ".")
        self.assertEqual(
            (bundle.bundle_path / "verifier.md").read_text(encoding="utf-8"),
            (PROJECT_ROOT / "src" / "harness" / "resources" / "verifier.md").read_text(
                encoding="utf-8"
            ),
        )

    def test_ignores_repository_prompt_override(self) -> None:
        self._create_task()
        self._write("prompts/verifier.md", "repository override must not be bundled\n")

        bundle = self._bundle(self._run().run_id)

        self.assertEqual(
            (bundle.bundle_path / "verifier.md").read_text(encoding="utf-8"),
            (PROJECT_ROOT / "src" / "harness" / "resources" / "verifier.md").read_text(
                encoding="utf-8"
            ),
        )

    def test_manifest_hashes_and_total_size_match_payloads(self) -> None:
        self._create_task()
        bundle = self._bundle(self._run().run_id)
        manifest = self._manifest(bundle.bundle_path)

        self.assertEqual(manifest, bundle.manifest)
        for entry in manifest["files"]:
            contents = (bundle.bundle_path / entry["path"]).read_bytes()
            self.assertEqual(entry["sha256"], hashlib.sha256(contents).hexdigest())
            self.assertEqual(entry["size_bytes"], len(contents))
        self.assertEqual(
            manifest["total_size_bytes"],
            sum(entry["size_bytes"] for entry in manifest["files"]),
        )
        without_hash = {key: value for key, value in manifest.items() if key != "bundle_sha256"}
        canonical = json.dumps(
            without_hash,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        self.assertEqual(manifest["bundle_sha256"], hashlib.sha256(canonical).hexdigest())

    def test_rejects_missing_evidence(self) -> None:
        self._create_task()

        with self.assertRaises(BundleEvidenceError):
            self._bundle("missing-run")

        self.assertFalse((self.root / "bundle").exists())

    def test_rejects_task_run_mismatch(self) -> None:
        self._create_task(task_id="TASK-FIRST")
        self._create_task(task_id="TASK-SECOND")
        run = self._run("TASK-FIRST")
        copied_run = self.repository / ".harness" / "evidence" / "TASK-SECOND" / run.run_id
        copied_run.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(run.evidence_path, copied_run)

        with self.assertRaises(BundleInputError):
            self._bundle(run.run_id, task_id="TASK-SECOND")

    def test_redacts_known_local_roots_without_serializing_environment(self) -> None:
        self._create_task(
            checks=[
                self._python_check(
                    "paths",
                    "from pathlib import Path; "
                    "print(Path.home()); "
                    "print(Path.cwd()); "
                    "print(next((Path.cwd() / '.harness/evidence/TASK-BUNDLE').iterdir()))",
                )
            ]
        )
        environment_name = "OUTCOME_HARNESS_BUNDLE_TEST_SECRET"
        environment_value = "must-not-be-serialized"
        previous = os.environ.get(environment_name)
        os.environ[environment_name] = environment_value
        try:
            bundle = self._bundle(self._run().run_id)
        finally:
            if previous is None:
                os.environ.pop(environment_name, None)
            else:
                os.environ[environment_name] = previous

        contents = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in bundle.bundle_path.rglob("*")
            if path.is_file()
        )
        self.assertNotIn(str(self.repository.resolve()), contents)
        self.assertNotIn(str(Path.home().resolve()), contents)
        self.assertNotIn(environment_name, contents)
        self.assertNotIn(environment_value, contents)
        self.assertIn("<HOME>", contents)
        self.assertIn("./.harness/evidence/TASK-BUNDLE/", contents)
        self.assertNotIn("<ABSOLUTE_PATH>", contents)

    def test_preserves_nonlocal_path_literals_in_json_diff_and_check_logs(self) -> None:
        paths = (
            "/api/v1/users",
            "/usr/bin/env python3",
            "https://example.com/api",
            "/app/config",
            r"C:\Program Files\Example",
            r"\\server\share\file",
        )
        payload = "\n".join(paths) + "\n"
        program = (
            "import sys; "
            f"payload={payload!r}; "
            "sys.stdout.write(payload); "
            "sys.stderr.write(payload)"
        )
        self._create_task(
            checks=[self._python_check("path-literals", program)],
            objective=payload,
        )
        self._write("src/example.txt", payload)
        run = verify_task("TASK-BUNDLE", cwd=self.repository)
        original_diff = (run.evidence_path / "diff.patch").read_bytes()
        original_checks = json.loads(
            (run.evidence_path / "checks.json").read_text(encoding="utf-8")
        )
        original_stdout_path = run.evidence_path / original_checks["checks"][0]["stdout_path"]
        original_stderr_path = run.evidence_path / original_checks["checks"][0]["stderr_path"]
        original_stdout = original_stdout_path.read_bytes()
        original_stderr = original_stderr_path.read_bytes()

        bundle = self._bundle(run.run_id)

        task = json.loads((bundle.bundle_path / "task.json").read_text(encoding="utf-8"))
        diff_patch = (bundle.bundle_path / "diff.patch").read_text(encoding="utf-8")
        checks = json.loads(
            (bundle.bundle_path / "checks.json").read_text(encoding="utf-8")
        )
        stdout = (
            bundle.bundle_path / checks["checks"][0]["stdout_path"]
        ).read_text(encoding="utf-8")
        stderr = (
            bundle.bundle_path / checks["checks"][0]["stderr_path"]
        ).read_text(encoding="utf-8")

        self.assertEqual(task["objective"], payload)
        self.assertEqual(checks["checks"][0]["argv"][2], program)
        self.assertEqual(stdout, payload)
        self.assertEqual(stderr, payload)
        for path in paths:
            with self.subTest(path=path):
                self.assertIn(path, diff_patch)
        self.assertNotIn("<ABSOLUTE_PATH>", diff_patch)
        self.assertNotIn("<ABSOLUTE_PATH>", stdout)
        self.assertNotIn("<ABSOLUTE_PATH>", stderr)
        self.assertEqual((run.evidence_path / "diff.patch").read_bytes(), original_diff)
        self.assertEqual(original_stdout_path.read_bytes(), original_stdout)
        self.assertEqual(original_stderr_path.read_bytes(), original_stderr)

    def test_preserves_arbitrary_non_utf8_check_output_bytes(self) -> None:
        stdout = b"stdout-before-\xff\x00-after\n"
        stderr = b"stderr-before-\xfe\x80-after\n"
        program = (
            "import os; "
            f"os.write(1, {stdout!r}); "
            f"os.write(2, {stderr!r})"
        )
        self._create_task(checks=[self._python_check("raw-bytes", program)])
        run = self._run()
        evidence_checks = json.loads(
            (run.evidence_path / "checks.json").read_text(encoding="utf-8")
        )
        evidence_stdout = run.evidence_path / evidence_checks["checks"][0]["stdout_path"]
        evidence_stderr = run.evidence_path / evidence_checks["checks"][0]["stderr_path"]

        bundle = self._bundle(run.run_id)
        checks = json.loads(
            (bundle.bundle_path / "checks.json").read_text(encoding="utf-8")
        )
        check = checks["checks"][0]

        self.assertEqual(
            (bundle.bundle_path / check["stdout_path"]).read_bytes(),
            stdout,
        )
        self.assertEqual(
            (bundle.bundle_path / check["stderr_path"]).read_bytes(),
            stderr,
        )
        self.assertEqual(evidence_stdout.read_bytes(), stdout)
        self.assertEqual(evidence_stderr.read_bytes(), stderr)

    def test_redacts_structured_keys_values_and_known_root_spellings(self) -> None:
        sanitized = _sanitize_value(
            {str(PROJECT_ROOT): str(Path.home())},
            _path_replacements(PROJECT_ROOT),
        )
        self.assertEqual(sanitized, {".": "<HOME>"})

        for root, replacement in ((PROJECT_ROOT, "."), (Path.home(), "<HOME>")):
            for spelling in _path_spellings(root):
                with self.subTest(root=root, spelling=spelling):
                    separator = "\\" if "\\" in spelling else "/"
                    self.assertEqual(
                        _sanitize_text(
                            f'"{spelling}{separator}child{separator}file.txt"',
                            _path_replacements(PROJECT_ROOT),
                        ),
                        f'"{replacement}{separator}child{separator}file.txt"',
                    )
                    self.assertEqual(
                        _sanitize_text(
                            f'"{spelling}"',
                            _path_replacements(PROJECT_ROOT),
                        ),
                        f'"{replacement}"',
                    )

        alias_root = Path("/var/folders/harness-c0/repository")
        spellings = _path_spellings(alias_root)
        self.assertIn("/var/folders/harness-c0/repository", spellings)
        self.assertIn("/private/var/folders/harness-c0/repository", spellings)
        for spelling in spellings:
            with self.subTest(alias_spelling=spelling):
                separator = "\\" if "\\" in spelling else "/"
                self.assertEqual(
                    _sanitize_text(
                        f"{spelling}{separator}artifact.log",
                        _path_replacements(alias_root),
                    ),
                    f".{separator}artifact.log",
                )

    def test_does_not_include_gitignored_worktree_files(self) -> None:
        self._create_task()
        self._write("ignored.txt", "do-not-bundle\n")
        bundle = self._bundle(self._run().run_id)

        contents = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in bundle.bundle_path.rglob("*")
            if path.is_file()
        )
        self.assertNotIn("ignored.txt", contents)
        self.assertNotIn("do-not-bundle", contents)

    def test_bundle_json_escapes_lone_surrogates(self) -> None:
        path = "src/" + os.fsdecode(b"non-utf8-\xff.txt")

        contents = _pretty_json_bytes({"path": path})

        self.assertIn(b"\\udcff", contents)
        self.assertEqual(json.loads(contents)["path"], path)

    @unittest.skipUnless(os.name == "posix", "requires POSIX surrogateescaped Git paths")
    def test_bundles_non_utf8_git_path_as_escaped_json(self) -> None:
        self._create_task()
        filename = os.fsdecode(b"non-utf8-\xff.txt")
        try:
            self._write(f"src/{filename}", b"changed\n")
        except OSError as error:
            self.skipTest(f"filesystem rejects non-UTF-8 paths: {error}")
        run = verify_task("TASK-BUNDLE", cwd=self.repository)

        bundle = self._bundle(run.run_id)

        changed_bytes = (bundle.bundle_path / "changed-files.json").read_bytes()
        changed = json.loads(changed_bytes)
        self.assertIn(b"\\udcff", changed_bytes)
        self.assertIn(
            f"src/{filename}",
            {change["path"] for change in changed["changes"]},
        )

    def test_rejects_check_result_that_disagrees_with_exit_code(self) -> None:
        self._create_task()
        run = self._run()
        checks_path = run.evidence_path / "checks.json"
        checks = json.loads(checks_path.read_text(encoding="utf-8"))
        checks["checks"][0]["passed"] = False
        checks_path.write_text(json.dumps(checks), encoding="utf-8")

        with self.assertRaises(BundleEvidenceError):
            self._bundle(run.run_id)

    @unittest.skipUnless(os.name == "posix", "symlink escape coverage requires POSIX")
    def test_rejects_log_symlink_swap_after_validation(self) -> None:
        self._create_task()
        run = self._run()
        checks = json.loads(
            (run.evidence_path / "checks.json").read_text(encoding="utf-8")
        )
        log_path = run.evidence_path / checks["checks"][0]["stdout_path"]
        outside = self.root / "outside.log"
        outside.write_text("outside\n", encoding="utf-8")

        def swap_log_after_validation(*args, **kwargs):
            validated_run = validate_run(*args, **kwargs)
            log_path.unlink()
            log_path.symlink_to(outside)
            return validated_run

        with mock.patch(
            "harness.bundle.validate_run",
            side_effect=swap_log_after_validation,
        ):
            with self.assertRaises(BundleEvidenceError):
                self._bundle(run.run_id)

    def test_removes_partial_output_when_bundle_write_fails(self) -> None:
        self._create_task()
        run = self._run()
        destination = self.root / "atomic-bundle"
        original_write_bytes = Path.write_bytes

        def fail_on_diff(path: Path, contents: bytes) -> int:
            if path.name == "diff.patch":
                raise OSError("simulated bundle write failure")
            return original_write_bytes(path, contents)

        with mock.patch.object(Path, "write_bytes", autospec=True, side_effect=fail_on_diff):
            with self.assertRaisesRegex(OSError, "simulated bundle write failure"):
                create_verification_bundle(
                    "TASK-BUNDLE",
                    run.run_id,
                    destination,
                    cwd=self.repository,
                )

        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob(".atomic-bundle.*")), [])

    def test_cli_exports_requested_task_run(self) -> None:
        self._create_task()
        run = self._run()
        output = io.StringIO()
        destination = self.root / "cli-bundle"

        with change_directory(self.repository), contextlib.redirect_stdout(output):
            self.assertEqual(
                cli.main(
                    [
                        "verifier",
                        "bundle",
                        "TASK-BUNDLE",
                        "--run-id",
                        run.run_id,
                        "--output",
                        str(destination),
                    ]
                ),
                0,
            )

        response = json.loads(output.getvalue())
        self.assertEqual(response["task_id"], "TASK-BUNDLE")
        self.assertEqual(response["run_id"], run.run_id)
        self.assertEqual(Path(response["bundle_path"]), destination.resolve())
        self.assertTrue(Path(response["manifest_path"]).is_file())
        self.assertGreater(response["total_size_bytes"], 0)


@unittest.skipUnless(Draft202012Validator, "install the test extra to run JSON Schema parity")
class BundleSchemaParityTests(unittest.TestCase):
    """Keep the emitted bundle manifest aligned with its public schema."""

    def test_manifest_matches_bundle_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            repository.mkdir()
            subprocess.run(["git", "init", "--quiet"], cwd=repository, check=True)
            (repository / ".harness").mkdir()
            (repository / ".harness" / "checks.json").write_text('{"checks": []}\n')
            (repository / "src").mkdir()
            (repository / "src" / "example.txt").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repository, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Harness Test",
                    "-c",
                    "user.email=harness-test@example.invalid",
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
                "objective": "Validate bundle schema.",
                "scope": ["src"],
                "checks": [
                    {
                        "name": "ok",
                        "argv": [sys.executable, "-c", "print('ok')"],
                        "required": True,
                    }
                ],
                "risk": "low",
                "verifier": {"required": True},
            }
            source = root / "task.json"
            source.write_text(json.dumps(specification), encoding="utf-8")
            create_task(source, cwd=repository)
            (repository / "src" / "example.txt").write_text("changed\n", encoding="utf-8")
            run = verify_task("TASK-SCHEMA", cwd=repository)
            bundle = create_verification_bundle(
                "TASK-SCHEMA", run.run_id, root / "bundle", cwd=repository
            )

            schema = json.loads(
                (PROJECT_ROOT / "schemas" / "bundle.schema.json").read_text(encoding="utf-8")
            )
            validator = Draft202012Validator(schema, format_checker=FormatChecker())
            self.assertEqual(list(validator.iter_errors(bundle.manifest)), [])
