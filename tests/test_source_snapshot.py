"""Integration tests for the canonical baseline-relative source snapshot."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import harness.gitdiff as gitdiff
import harness.source_snapshot as source_snapshot
from harness.source_snapshot import (
    SOURCE_HASH_CHUNK_SIZE,
    SourceSnapshot,
    SourceSnapshotEntry,
    SourceSnapshotError,
    collect_source_snapshot,
)


class SourceSnapshotRepositoryTests(unittest.TestCase):
    """Exercise the public API against an actual disposable Git repository."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self._git("init", "--quiet")
        self._write(".gitignore", "*.ignored\nignored-dir/\n")
        self._write("src/base.txt", "base\n")
        self._write("src/delete.txt", "delete\n")
        self._write("src/rename.txt", "rename\n")
        self._write("src/nested/data.txt", "inside\n")
        self._write("src/script.sh", "#!/bin/sh\nexit 0\n")
        self._write("binary.bin", b"\x00baseline\xff\n")
        self._write("empty.txt", b"")
        self._git("add", ".")
        self._commit("baseline")
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

    def _git_bytes(self, *arguments: str) -> bytes:
        result = subprocess.run(
            ["git", *arguments],
            cwd=self.repository,
            check=True,
            capture_output=True,
        )
        return result.stdout

    def _commit(self, message: str, *, allow_empty: bool = False) -> None:
        arguments = [
            "-c",
            "user.name=Harness Test",
            "-c",
            "user.email=harness-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            message,
        ]
        if allow_empty:
            arguments.insert(6, "--allow-empty")
        self._git(*arguments)

    def _write(self, relative_path: str, contents: str | bytes) -> Path:
        path = self.repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contents, bytes):
            path.write_bytes(contents)
        else:
            path.write_text(contents, encoding="utf-8")
        return path

    def _task(
        self,
        *,
        baseline: str | None = None,
        scope: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "baseline": self.baseline if baseline is None else baseline,
            "scope": ["src"] if scope is None else scope,
            "checks": [{"name": "ignored-by-snapshot"}],
        }

    def _snapshot(
        self,
        task: dict[str, object] | None = None,
    ) -> SourceSnapshot:
        return collect_source_snapshot(
            self._task() if task is None else task,
            cwd=self.repository,
        )

    @staticmethod
    def _entries(snapshot: SourceSnapshot) -> dict[str, SourceSnapshotEntry]:
        return {entry.path: entry for entry in snapshot.entries}

    def test_clean_snapshot_has_exact_canonical_digest_and_frozen_values(self) -> None:
        snapshot = self._snapshot()
        document = snapshot.to_document()
        payload = {
            "schema_version": 1,
            "baseline": self.baseline,
            "entries": [],
        }
        expected_digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
        ).hexdigest()

        self.assertEqual(snapshot.schema_version, 1)
        self.assertEqual(snapshot.baseline, self.baseline)
        self.assertEqual(len(snapshot.baseline), len(self.baseline))
        self.assertEqual(snapshot.entries, ())
        self.assertEqual(snapshot.snapshot_sha256, expected_digest)
        self.assertEqual(document, {**payload, "snapshot_sha256": expected_digest})
        self.assertNotIn("timestamp", json.dumps(document))
        self.assertNotIn(str(self.repository), json.dumps(document))
        with self.assertRaises(FrozenInstanceError):
            snapshot.baseline = "different"  # type: ignore[misc]

    def test_baseline_commit_identity_ignores_git_replace_refs(self) -> None:
        self._write("src/base.txt", "replacement\n")
        self._git("add", "src/base.txt")
        self._commit("replacement target")
        replacement_commit = self._git("rev-parse", "HEAD")
        self._write("src/base.txt", "base\n")
        self._git("replace", self.baseline, replacement_commit)

        with_replace = self._snapshot()
        self._git("replace", "-d", self.baseline)
        without_replace = self._snapshot()

        self.assertEqual(with_replace, without_replace)
        self.assertEqual(with_replace.entries, ())

    def test_canonical_serialization_is_sorted_and_sensitive_to_every_field(self) -> None:
        entry = {
            "path": "src/value.txt",
            "state": "present",
            "mode": "100644",
            "size_bytes": 5,
            "sha256": "a" * 64,
        }
        payload = {
            "schema_version": 1,
            "baseline": "b" * 40,
            "entries": [entry],
        }
        canonical = source_snapshot._canonical_json_bytes(payload)
        reordered = {
            "entries": [
                {
                    "sha256": "a" * 64,
                    "size_bytes": 5,
                    "mode": "100644",
                    "state": "present",
                    "path": "src/value.txt",
                }
            ],
            "baseline": "b" * 40,
            "schema_version": 1,
        }
        self.assertEqual(
            source_snapshot._canonical_json_bytes(reordered),
            canonical,
        )

        variants = [
            {**payload, "schema_version": 2},
            {**payload, "baseline": "c" * 40},
        ]
        for field, value in (
            ("path", "src/other.txt"),
            ("state", "deleted"),
            ("mode", "100755"),
            ("size_bytes", 6),
            ("sha256", "d" * 64),
        ):
            variants.append(
                {
                    **payload,
                    "entries": [{**entry, field: value}],
                }
            )

        original_digest = hashlib.sha256(canonical).hexdigest()
        for variant in variants:
            with self.subTest(variant=variant):
                self.assertNotEqual(
                    hashlib.sha256(
                        source_snapshot._canonical_json_bytes(variant)
                    ).hexdigest(),
                    original_digest,
                )

    def test_api_uses_only_task_baseline_and_ignores_scope_and_checks(self) -> None:
        self._write("docs/outside.txt", "outside\n")
        first = self._snapshot()
        second = self._snapshot(
            {
                "baseline": self.baseline,
                "scope": ["unrelated"],
                "checks": [],
            }
        )

        self.assertEqual(first, second)
        with self.assertRaises(TypeError):
            collect_source_snapshot(  # type: ignore[call-arg]
                self._task(),
                cwd=self.repository,
                base_ref="HEAD",
            )

    def test_baseline_identity_is_part_of_the_digest_even_for_the_same_tree(self) -> None:
        self._commit("same tree", allow_empty=True)
        second_baseline = self._git("rev-parse", "HEAD")

        from_first = self._snapshot(self._task(baseline=self.baseline))
        from_second = self._snapshot(self._task(baseline=second_baseline))

        self.assertEqual(from_first.entries, ())
        self.assertEqual(from_second.entries, ())
        self.assertNotEqual(from_first.baseline, from_second.baseline)
        self.assertNotEqual(from_first.snapshot_sha256, from_second.snapshot_sha256)

    def test_rejects_missing_noncommit_and_nonrepository_baselines(self) -> None:
        tree_id = self._git("rev-parse", "HEAD^{tree}")
        for label, task in (
            ("missing", self._task(baseline="refs/heads/does-not-exist")),
            ("tree", self._task(baseline=tree_id)),
        ):
            with self.subTest(label=label):
                with self.assertRaises(SourceSnapshotError):
                    self._snapshot(task)

        outside = self.root / "outside"
        outside.mkdir()
        with self.assertRaises(SourceSnapshotError):
            collect_source_snapshot(self._task(), cwd=outside)

    def test_hashes_text_binary_empty_large_and_out_of_scope_files(self) -> None:
        changed_text = self._write("src/base.txt", "changed\n").read_bytes()
        changed_binary = self._write("binary.bin", b"\x00changed\xfe\n").read_bytes()
        empty = self._write("new empty.txt", b"").read_bytes()
        large = self._write(
            "large.bin",
            b"x" * (SOURCE_HASH_CHUNK_SIZE * 2 + 17),
        ).read_bytes()
        outside = self._write("docs/outside.txt", "outside\n").read_bytes()

        snapshot = self._snapshot()
        entries = self._entries(snapshot)
        expected = {
            "src/base.txt": changed_text,
            "binary.bin": changed_binary,
            "new empty.txt": empty,
            "large.bin": large,
            "docs/outside.txt": outside,
        }

        self.assertEqual(set(entries), set(expected))
        self.assertEqual(
            [entry.path for entry in snapshot.entries],
            sorted(expected, key=lambda path: path.encode("utf-8")),
        )
        for path, contents in expected.items():
            with self.subTest(path=path):
                entry = entries[path]
                self.assertEqual(entry.state, "present")
                self.assertEqual(entry.mode, "100644")
                self.assertEqual(entry.size_bytes, len(contents))
                self.assertEqual(entry.sha256, hashlib.sha256(contents).hexdigest())
                self.assertFalse(hasattr(entry, "content"))

    def test_deletion_and_rename_are_final_path_entries(self) -> None:
        (self.repository / "src" / "delete.txt").unlink()
        self._git("mv", "src/rename.txt", "src/renamed.txt")
        renamed = self._write("src/renamed.txt", "renamed and changed\n").read_bytes()

        entries = self._entries(self._snapshot())

        for path in ("src/delete.txt", "src/rename.txt"):
            with self.subTest(path=path):
                self.assertEqual(
                    entries[path],
                    SourceSnapshotEntry(
                        path=path,
                        state="deleted",
                        mode=None,
                        size_bytes=None,
                        sha256=None,
                    ),
                )
        self.assertEqual(entries["src/renamed.txt"].state, "present")
        self.assertEqual(
            entries["src/renamed.txt"].sha256,
            hashlib.sha256(renamed).hexdigest(),
        )
        self.assertNotIn("renamed", {entry.state for entry in entries.values()})

    @unittest.skipUnless(os.name == "posix", "executable mode requires POSIX")
    def test_executable_mode_changes_source_identity(self) -> None:
        if self._git("config", "--bool", "core.filemode") == "false":
            self.skipTest("Git is configured to ignore executable mode")
        path = self.repository / "src" / "script.sh"
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

        entry = self._entries(self._snapshot())["src/script.sh"]

        self.assertEqual(entry.state, "present")
        self.assertEqual(entry.mode, "100755")

    @unittest.skipUnless(os.name == "posix", "executable mode requires POSIX")
    def test_core_filemode_false_does_not_hide_executable_mode(self) -> None:
        path = self.repository / "src" / "script.sh"
        path.chmod(path.stat().st_mode & ~0o111)
        self._git("config", "core.filemode", "false")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        if not path.stat().st_mode & stat.S_IXUSR:
            self.skipTest("filesystem does not preserve executable mode")
        self.assertEqual(
            self._git_bytes(
                "diff",
                "--raw",
                "-z",
                self.baseline,
                "--",
                "src/script.sh",
            ),
            b"",
        )

        entry = self._entries(self._snapshot())["src/script.sh"]

        self.assertEqual(entry.mode, "100755")

    def test_assume_unchanged_does_not_hide_worktree_bytes(self) -> None:
        path = self.repository / "src" / "base.txt"
        self._git("update-index", "--assume-unchanged", "src/base.txt")
        try:
            contents = self._write("src/base.txt", "hidden by index hint\n").read_bytes()
            self.assertEqual(
                self._git_bytes(
                    "diff",
                    "--raw",
                    "-z",
                    self.baseline,
                    "--",
                    "src/base.txt",
                ),
                b"",
            )

            entry = self._entries(self._snapshot())["src/base.txt"]

            self.assertEqual(entry.sha256, hashlib.sha256(contents).hexdigest())
        finally:
            path.write_text("base\n", encoding="utf-8")
            self._git("update-index", "--no-assume-unchanged", "src/base.txt")

    def test_skip_worktree_does_not_hide_worktree_bytes(self) -> None:
        path = self.repository / "src" / "base.txt"
        self._git("update-index", "--skip-worktree", "src/base.txt")
        try:
            contents = self._write("src/base.txt", "hidden by skip-worktree\n").read_bytes()
            self.assertEqual(
                self._git_bytes(
                    "diff",
                    "--raw",
                    "-z",
                    self.baseline,
                    "--",
                    "src/base.txt",
                ),
                b"",
            )

            entry = self._entries(self._snapshot())["src/base.txt"]

            self.assertEqual(entry.sha256, hashlib.sha256(contents).hexdigest())
        finally:
            path.write_text("base\n", encoding="utf-8")
            self._git("update-index", "--no-skip-worktree", "src/base.txt")

    def test_clean_filter_does_not_replace_raw_worktree_bytes(self) -> None:
        self._git("config", "core.autocrlf", "false")
        self._write(".gitattributes", "filtered.txt ident\n")
        self._write("filtered.txt", b"$Id$\n")
        self._git("add", ".gitattributes", "filtered.txt")
        self._commit("filtered baseline")
        self.baseline = self._git("rev-parse", "HEAD")
        path = self.repository / "filtered.txt"
        path.unlink()
        self._git("checkout", "--", "filtered.txt")
        baseline_contents = self._git_bytes(
            "show",
            f"{self.baseline}:filtered.txt",
        )
        worktree_contents = path.read_bytes()
        self.assertNotEqual(worktree_contents, baseline_contents)
        self.assertEqual(
            self._git("status", "--porcelain", "--", "filtered.txt"),
            "",
        )

        entry = self._entries(self._snapshot())["filtered.txt"]

        self.assertEqual(entry.size_bytes, len(worktree_contents))
        self.assertEqual(
            entry.sha256,
            hashlib.sha256(worktree_contents).hexdigest(),
        )

    def test_unstaged_staged_and_committed_final_content_are_identical(self) -> None:
        self._write("src/base.txt", "final\n")
        unstaged = self._snapshot()
        self._git("add", "src/base.txt")
        staged = self._snapshot()
        self._commit("final content")
        committed = self._snapshot()

        self.assertEqual(unstaged, staged)
        self.assertEqual(staged, committed)

    def test_staged_change_reverted_in_worktree_collapses_to_clean(self) -> None:
        clean = self._snapshot()
        self._write("src/base.txt", "staged\n")
        self._git("add", "src/base.txt")
        self._write("src/base.txt", "base\n")

        self.assertEqual(self._snapshot(), clean)

    def test_file_replaced_by_directory_does_not_depend_on_index_history(self) -> None:
        path = self._write("added-after-baseline", "tracked file\n")
        self._git("add", "added-after-baseline")
        self._commit("add file after baseline")
        path.unlink()
        path.mkdir()
        child_contents = self._write(
            "added-after-baseline/child.txt",
            "final child\n",
        ).read_bytes()

        with_tracked_file_history = self._snapshot()
        self._git(
            "update-index",
            "--force-remove",
            "--",
            "added-after-baseline",
        )
        without_tracked_file_history = self._snapshot()

        self.assertEqual(
            with_tracked_file_history,
            without_tracked_file_history,
        )
        entries = self._entries(with_tracked_file_history)
        self.assertNotIn("added-after-baseline", entries)
        self.assertEqual(
            entries["added-after-baseline/child.txt"].sha256,
            hashlib.sha256(child_contents).hexdigest(),
        )

    def test_directory_replaced_by_file_does_not_depend_on_index_history(self) -> None:
        self._write("tracked-directory/child.txt", "tracked child\n")
        self._git("add", "tracked-directory/child.txt")
        self._commit("add directory contents after baseline")
        shutil.rmtree(self.repository / "tracked-directory")
        final_contents = self._write(
            "tracked-directory",
            "final file\n",
        ).read_bytes()

        with_tracked_child_history = self._snapshot()
        self._git(
            "update-index",
            "--force-remove",
            "--",
            "tracked-directory/child.txt",
        )
        without_tracked_child_history = self._snapshot()

        self.assertEqual(
            with_tracked_child_history,
            without_tracked_child_history,
        )
        entries = self._entries(with_tracked_child_history)
        self.assertNotIn("tracked-directory/child.txt", entries)
        self.assertEqual(
            entries["tracked-directory"].sha256,
            hashlib.sha256(final_contents).hexdigest(),
        )

    def test_staged_deletion_recreated_from_baseline_collapses_to_clean(self) -> None:
        clean = self._snapshot()
        self._git("rm", "--quiet", "src/base.txt")
        self._write("src/base.txt", "base\n")

        self.assertEqual(self._snapshot(), clean)

    def test_restoring_changed_source_to_baseline_restores_clean_digest(self) -> None:
        clean = self._snapshot()
        self._write("src/base.txt", "changed\n")
        changed = self._snapshot()
        self._write("src/base.txt", "base\n")

        self.assertNotEqual(changed.snapshot_sha256, clean.snapshot_sha256)
        self.assertEqual(self._snapshot(), clean)

    def test_candidate_and_git_output_order_do_not_change_the_snapshot(self) -> None:
        self._write("z-last.txt", "z\n")
        self._write("a-first.txt", "a\n")
        expected = self._snapshot()
        original_parse = gitdiff._parse_raw_diff
        original_untracked = gitdiff._untracked_paths

        with (
            mock.patch.object(
                gitdiff,
                "_parse_raw_diff",
                side_effect=lambda output: list(reversed(original_parse(output))),
            ),
            mock.patch.object(
                gitdiff,
                "_untracked_paths",
                side_effect=lambda repository: list(
                    reversed(original_untracked(repository))
                ),
            ),
        ):
            reordered = self._snapshot()

        self.assertEqual(reordered, expected)

    def test_excludes_ignored_git_and_canonical_metadata_only(self) -> None:
        excluded = (
            ".harness/tasks/TASK-X.json",
            ".harness/evidence/TASK-X/run.txt",
            ".harness/runs.jsonl",
            ".harness/lessons.md",
            ".harness/config.json",
            "generated.ignored",
        )
        for path in excluded:
            self._write(path, "excluded\n")
        self._write(".git/snapshot-private", "private\n")
        included = (
            ".harness/tasks-extra/product.txt",
            ".harness/checks.json",
            "docs/outside.txt",
        )
        for path in included:
            self._write(path, "included\n")

        paths = set(self._entries(self._snapshot()))

        self.assertEqual(paths, set(included))

    def test_preserves_spaces_unicode_and_newline_paths(self) -> None:
        paths = [
            "space name.txt",
            "한글 이름.txt",
            "line\nbreak.txt",
            "-leading-dash.txt",
        ]
        if os.name == "posix":
            paths.extend(("a:colon.txt", "back\\slash.txt"))
        for path in paths:
            self._write(path, path.encode("utf-8"))

        snapshot = self._snapshot()

        self.assertEqual(set(self._entries(snapshot)), set(paths))
        json.dumps(snapshot.to_document(), ensure_ascii=True)

    @unittest.skipUnless(os.name == "posix", "requires POSIX byte filenames")
    def test_surrogateescaped_non_utf8_path_has_canonical_json(self) -> None:
        filename = os.fsdecode(b"non-utf8-\xff.txt")
        path = self.repository / filename
        try:
            path.write_bytes(b"bytes\n")
        except OSError as error:
            self.skipTest(f"filesystem rejects non-UTF-8 paths: {error}")

        snapshot = self._snapshot()
        document_bytes = json.dumps(
            snapshot.to_document(),
            ensure_ascii=True,
            sort_keys=True,
        ).encode("ascii")

        self.assertIn(filename, self._entries(snapshot))
        self.assertIn(b"\\udcff", document_bytes)

    def test_collection_is_read_only_for_git_and_harness_state(self) -> None:
        self._write("src/base.txt", "changed\n")
        before_status = self._git_bytes("status", "--porcelain=v2", "-z")
        self.assertFalse((self.repository / ".harness").exists())

        self._snapshot()

        self.assertEqual(
            self._git_bytes("status", "--porcelain=v2", "-z"),
            before_status,
        )
        self.assertFalse((self.repository / ".harness").exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unavailable")
    def test_symlinks_hash_target_text_without_following_targets(self) -> None:
        outside = self.root / "outside.txt"
        outside.write_text("outside one\n", encoding="utf-8")
        targets = {
            "src/internal-link": "base.txt",
            "src/outside-link": str(outside),
            "src/broken-link": "missing-target",
        }
        for path, target in targets.items():
            os.symlink(target, self.repository / path)

        first = self._snapshot()
        entries = self._entries(first)
        for path, target in targets.items():
            with self.subTest(path=path):
                target_bytes = os.fsencode(target)
                self.assertEqual(entries[path].mode, "120000")
                self.assertEqual(entries[path].size_bytes, len(target_bytes))
                self.assertEqual(
                    entries[path].sha256,
                    hashlib.sha256(target_bytes).hexdigest(),
                )

        outside.write_text("outside two\n", encoding="utf-8")
        self.assertEqual(self._snapshot(), first)
        broken = self.repository / "src" / "broken-link"
        broken.unlink()
        os.symlink("different-missing-target", broken)
        self.assertNotEqual(self._snapshot().snapshot_sha256, first.snapshot_sha256)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unavailable")
    def test_clean_tracked_symlink_is_inherited_from_the_baseline(self) -> None:
        os.symlink("base.txt", self.repository / "src" / "tracked-link")
        self._git("add", "src/tracked-link")
        self._commit("tracked symlink")
        self.baseline = self._git("rev-parse", "HEAD")

        self.assertEqual(self._snapshot().entries, ())

    @unittest.skipUnless(
        os.name == "posix" and hasattr(os, "symlink"),
        "parent symlink safety requires POSIX",
    )
    def test_parent_symlink_is_present_and_nested_baseline_file_is_deleted(self) -> None:
        outside = self.root / "outside-directory"
        outside.mkdir()
        (outside / "data.txt").write_text("must not be hashed\n", encoding="utf-8")
        nested = self.repository / "src" / "nested"
        shutil.rmtree(nested)
        os.symlink(str(outside), nested)

        first = self._snapshot()
        entries = self._entries(first)

        self.assertEqual(entries["src/nested/data.txt"].state, "deleted")
        self.assertEqual(entries["src/nested"].mode, "120000")
        outside.joinpath("data.txt").write_text("changed outside\n", encoding="utf-8")
        self.assertEqual(self._snapshot(), first)

    def test_gitlink_fails_closed(self) -> None:
        self._git(
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{self.baseline},vendor/submodule",
        )

        with self.assertRaisesRegex(SourceSnapshotError, "submodule"):
            self._snapshot()

    def test_unmerged_worktree_fails_closed(self) -> None:
        original_branch = self._git("branch", "--show-current")
        self._git("switch", "-c", "other")
        self._write("src/base.txt", "other\n")
        self._git("add", "src/base.txt")
        self._commit("other")
        self._git("switch", original_branch)
        self._write("src/base.txt", "ours\n")
        self._git("add", "src/base.txt")
        self._commit("ours")
        result = subprocess.run(
            [
                "git",
                "-c",
                "user.name=Harness Test",
                "-c",
                "user.email=harness-test@example.invalid",
                "merge",
                "other",
            ],
            cwd=self.repository,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(
            self._git_bytes("ls-files", "--unmerged", "-z", "--", "src/base.txt")
        )

        with self.assertRaisesRegex(SourceSnapshotError, "status 'U'"):
            self._snapshot()

    def test_staged_deleted_path_recreated_as_ignored_remains_deleted(self) -> None:
        self._write("tracked.ignored", "tracked baseline\n")
        self._git("add", "--force", "tracked.ignored")
        self._commit("tracked ignored file")
        self.baseline = self._git("rev-parse", "HEAD")
        self._git("rm", "--quiet", "tracked.ignored")
        self._write("tracked.ignored", "ignored recreation\n")

        entry = self._entries(self._snapshot())["tracked.ignored"]

        self.assertEqual(entry.state, "deleted")
        self.assertIsNone(entry.mode)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO is unavailable")
    def test_untracked_fifo_fails_closed_but_ignored_metadata_and_git_fifos_do_not(self) -> None:
        fifo = self.repository / "source.fifo"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(SourceSnapshotError, "FIFO"):
            self._snapshot()
        fifo.unlink()

        ignored = self.repository / "ignored.ignored"
        metadata = self.repository / ".harness" / "tasks" / "metadata.fifo"
        git_private = self.repository / ".git" / "private.fifo"
        metadata.parent.mkdir(parents=True)
        os.mkfifo(ignored)
        os.mkfifo(metadata)
        os.mkfifo(git_private)

        self.assertEqual(self._snapshot().entries, ())

    @unittest.skipUnless(hasattr(socket, "AF_UNIX"), "Unix sockets are unavailable")
    def test_untracked_socket_fails_closed_when_platform_allows_it(self) -> None:
        path = self.repository / "source.sock"
        source_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            try:
                source_socket.bind(str(path))
            except OSError as error:
                self.skipTest(f"platform cannot create a repository socket: {error}")
            with self.assertRaisesRegex(SourceSnapshotError, "socket"):
                self._snapshot()
        finally:
            source_socket.close()
            path.unlink(missing_ok=True)

    def test_device_file_modes_are_explicitly_unsupported(self) -> None:
        for label, file_mode in (
            ("character device", stat.S_IFCHR),
            ("block device", stat.S_IFBLK),
        ):
            with self.subTest(label=label):
                self.assertRegex(
                    str(source_snapshot._unsupported_file_type("device", file_mode)),
                    label,
                )

    def test_windows_symlink_placeholder_preserves_git_mode(self) -> None:
        candidate = gitdiff._FinalTreeCandidate(
            path="link",
            baseline_mode="120000",
            baseline_oid="abc",
            current_present=True,
            current_mode="120000",
        )
        source_stat = (self.repository / "src" / "base.txt").stat()

        with mock.patch.object(source_snapshot.os, "name", "nt"):
            self.assertEqual(
                source_snapshot._regular_mode(source_stat, candidate),
                "120000",
            )

    def test_large_file_hashing_is_chunked(self) -> None:
        self._write(
            "src/base.txt",
            b"x" * (SOURCE_HASH_CHUNK_SIZE * 2 + 23),
        )
        original_read = source_snapshot._read_hash_chunk
        chunk_sizes: list[int] = []

        def record_chunk(descriptor: int) -> bytes:
            chunk = original_read(descriptor)
            chunk_sizes.append(len(chunk))
            return chunk

        with mock.patch.object(
            source_snapshot,
            "_read_hash_chunk",
            side_effect=record_chunk,
        ):
            self._snapshot()

        self.assertGreaterEqual(
            sum(size > 0 for size in chunk_sizes),
            6,
        )
        self.assertLessEqual(max(chunk_sizes), SOURCE_HASH_CHUNK_SIZE)

    def test_mutation_deletion_and_replacement_during_hashing_fail_closed(self) -> None:
        target = self.repository / "src" / "base.txt"
        original_read = source_snapshot._read_hash_chunk

        def assert_unstable(action) -> None:
            self._write(
                "src/base.txt",
                b"x" * (SOURCE_HASH_CHUNK_SIZE * 2 + 29),
            )
            triggered = False
            target_stat = target.stat()

            def disturb_after_chunk(descriptor: int) -> bytes:
                nonlocal triggered
                chunk = original_read(descriptor)
                opened = os.fstat(descriptor)
                is_target = (
                    opened.st_dev == target_stat.st_dev
                    and opened.st_ino == target_stat.st_ino
                )
                if chunk and is_target and not triggered:
                    triggered = True
                    action()
                return chunk

            with (
                mock.patch.object(
                    source_snapshot,
                    "_read_hash_chunk",
                    side_effect=disturb_after_chunk,
                ),
                self.assertRaises(SourceSnapshotError),
            ):
                self._snapshot()

        with self.subTest(action="mutate"):
            assert_unstable(lambda: target.write_bytes(b"mutated\n"))
        with self.subTest(action="delete"):
            assert_unstable(target.unlink)
        with self.subTest(action="replace"):
            replacement = self.repository / "replacement.tmp"

            def replace() -> None:
                replacement.write_bytes(b"replacement\n")
                os.replace(replacement, target)

            assert_unstable(replace)

    def test_identical_byte_replacement_between_observations_fails_closed(self) -> None:
        target = self.repository / "src" / "base.txt"
        replacement = self.repository / "same-bytes.tmp"
        original_observe = source_snapshot._collect_snapshot_observation
        observations = 0

        def replace_after_first_observation(*args, **kwargs):
            nonlocal observations
            observation = original_observe(*args, **kwargs)
            observations += 1
            if observations == 1:
                replacement.write_bytes(target.read_bytes())
                os.replace(replacement, target)
            return observation

        with (
            mock.patch.object(
                source_snapshot,
                "_collect_snapshot_observation",
                side_effect=replace_after_first_observation,
            ),
            self.assertRaisesRegex(SourceSnapshotError, "changed"),
        ):
            self._snapshot()


if __name__ == "__main__":
    unittest.main()
