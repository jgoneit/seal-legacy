"""Integration tests for in-memory Git change collection."""

from __future__ import annotations

import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from harness.gitdiff import GitDiffRepositoryError, collect_changes


class GitDiffIntegrationTests(unittest.TestCase):
    """Exercise every collection layer against an actual disposable Git repository."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary_directory.name) / "repository"
        self.repository.mkdir()
        self._git("init", "--quiet")
        self._write(".gitignore", "*.ignored\n")
        self._write("src/foo/inside.txt", "inside\n")
        self._write("src/foobar/sibling.txt", "sibling\n")
        self._write("docs/guide.md", "guide\n")
        self._write("binary.bin", b"\x00fixture\n")
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
        self.baseline = self._git("rev-parse", "HEAD")

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

    def _task(self, scope: list[str] | None = None) -> dict[str, object]:
        return {
            "baseline": self.baseline,
            "scope": ["src/foo"] if scope is None else scope,
        }

    def _collect(self, scope: list[str] | None = None, *, base_ref: str | None = None):
        return collect_changes(self._task(scope), cwd=self.repository, base_ref=base_ref)

    def _change(self, collection, *, path: str, source: str | None = None):
        matches = [
            change
            for change in collection.changes
            if change.path == path and (source is None or change.source == source)
        ]
        self.assertEqual(matches and len(matches), 1, collection.changes)
        return matches[0]

    def test_in_scope_change_passes_scope_check(self) -> None:
        self._write("src/foo/inside.txt", "changed inside\n")

        collection = self._collect()

        change = self._change(collection, path="src/foo/inside.txt", source="unstaged")
        self.assertTrue(change.in_scope)
        self.assertEqual(collection.in_scope_changes, (change,))
        self.assertEqual(collection.out_of_scope_changes, ())
        self.assertTrue(collection.scope_passed)

    def test_out_of_scope_change_is_reported(self) -> None:
        self._write("docs/guide.md", "outside\n")

        collection = self._collect()

        change = self._change(collection, path="docs/guide.md", source="unstaged")
        self.assertFalse(change.in_scope)
        self.assertEqual(collection.out_of_scope_changes, (change,))
        self.assertFalse(collection.scope_passed)

    def test_scope_comparison_does_not_match_a_prefix_sibling(self) -> None:
        self._write("src/foo/Included.java", "class Included {}\n")
        self._write("src/foobar/Excluded.java", "class Excluded {}\n")

        collection = self._collect()

        self.assertEqual(
            {change.path for change in collection.in_scope_changes},
            {"src/foo/Included.java"},
        )
        self.assertEqual(
            {change.path for change in collection.out_of_scope_changes},
            {"src/foobar/Excluded.java"},
        )

    def test_detects_untracked_files(self) -> None:
        self._write("notes/untracked.txt", "untracked\n")

        collection = self._collect(["."])

        change = self._change(collection, path="notes/untracked.txt", source="untracked")
        self.assertEqual(change.status, "untracked")
        self.assertTrue(change.in_scope)

    def test_detects_staged_rename_with_both_paths(self) -> None:
        self._git("mv", "src/foo/inside.txt", "src/foo/renamed.txt")

        collection = self._collect()

        change = self._change(collection, path="src/foo/renamed.txt", source="staged")
        self.assertEqual(change.status, "renamed")
        self.assertEqual(change.previous_path, "src/foo/inside.txt")
        self.assertTrue(change.in_scope)

    def test_detects_staged_deletion(self) -> None:
        self._git("rm", "docs/guide.md")

        collection = self._collect(["docs"])

        change = self._change(collection, path="docs/guide.md", source="staged")
        self.assertEqual(change.status, "deleted")
        self.assertIsNone(change.new_mode)
        self.assertTrue(change.in_scope)

    def test_detects_staged_file_mode_change(self) -> None:
        path = self.repository / "src/foo/inside.txt"
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        self._git("add", "src/foo/inside.txt")

        collection = self._collect()

        change = self._change(collection, path="src/foo/inside.txt", source="staged")
        self.assertTrue(change.mode_changed)
        self.assertEqual(change.old_mode, "100644")
        self.assertEqual(change.new_mode, "100755")

    def test_marks_binary_changes_without_retaining_content(self) -> None:
        self._write("binary.bin", b"\x00changed\xff\n")
        self._git("add", "binary.bin")

        collection = self._collect(["."])

        change = self._change(collection, path="binary.bin", source="staged")
        self.assertTrue(change.is_binary)
        self.assertFalse(hasattr(change, "content"))

    def test_ignores_gitignored_files(self) -> None:
        self._write("generated.ignored", "ignored\n")
        self._write("visible.txt", "visible\n")

        collection = self._collect(["."])

        paths = {change.path for change in collection.changes}
        self.assertIn("visible.txt", paths)
        self.assertNotIn("generated.ignored", paths)

    def test_excludes_all_harness_metadata_paths_from_product_changes(self) -> None:
        metadata_paths = {
            ".harness/tasks/TASK-001.json",
            ".harness/evidence/TASK-001/check.txt",
            ".harness/runs.jsonl",
            ".harness/lessons.md",
            ".harness/config.json",
        }
        for path in metadata_paths:
            self._write(path, "metadata\n")
        self._write("src/foo/product.txt", "product\n")

        collection = self._collect(["."])

        self.assertEqual({change.path for change in collection.metadata_changes}, metadata_paths)
        self.assertEqual(
            {change.path for change in collection.product_changes},
            {"src/foo/product.txt"},
        )
        self.assertEqual(
            {change.path for change in collection.in_scope_changes},
            {"src/foo/product.txt"},
        )

    def test_base_ref_overrides_the_task_baseline(self) -> None:
        self._write("src/foo/committed.txt", "committed\n")
        self._git("add", "src/foo/committed.txt")
        self._git(
            "-c",
            "user.name=Harness Test",
            "-c",
            "user.email=harness-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "later change",
        )
        current_head = self._git("rev-parse", "HEAD")

        from_task_baseline = self._collect()
        from_override = self._collect(base_ref=current_head)

        self.assertEqual(from_task_baseline.base_ref, self.baseline)
        self.assertEqual(from_override.base_ref, current_head)
        committed_change = self._change(
            from_task_baseline,
            path="src/foo/committed.txt",
            source="committed",
        )
        self.assertEqual(committed_change.status, "added")
        self.assertNotIn(
            "src/foo/committed.txt",
            {change.path for change in from_override.changes},
        )

    def test_fails_clearly_outside_a_git_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(GitDiffRepositoryError, "inside an initialized Git repository"):
                collect_changes(self._task(), cwd=directory)
