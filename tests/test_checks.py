"""Process lifecycle coverage for verification checks."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from harness import checks


class CheckProcessLifecycleTests(unittest.TestCase):
    """Keep platform-specific process cleanup tied to its startup ownership."""

    def test_windows_start_assigns_the_check_to_a_job(self) -> None:
        process = mock.Mock(spec=subprocess.Popen)
        job = mock.sentinel.job
        stdout = mock.sentinel.stdout
        stderr = mock.sentinel.stderr
        cwd = Path("/repository")

        with (
            mock.patch.object(checks.os, "name", "nt"),
            mock.patch.object(
                checks.subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0x00000200,
                create=True,
            ),
            mock.patch.object(checks.subprocess, "Popen", return_value=process) as popen,
            mock.patch.object(checks, "_create_windows_job", return_value=job) as create_job,
        ):
            actual_process, actual_job = checks._start_process(
                ["check.exe", "--fast"], cwd, stdout, stderr
            )

        self.assertIs(actual_process, process)
        self.assertIs(actual_job, job)
        popen.assert_called_once_with(
            ["check.exe", "--fast"],
            cwd=str(cwd),
            stdout=stdout,
            stderr=stderr,
            shell=False,
            creationflags=0x00000200,
        )
        create_job.assert_called_once_with(process)

    def test_windows_success_cleanup_closes_job_without_taskkill(self) -> None:
        job = mock.Mock()

        with (
            mock.patch.object(checks.os, "name", "nt"),
            mock.patch.object(checks, "_terminate_windows_tree") as terminate_tree,
        ):
            checks._reap_finished_process_group(mock.sentinel.process, job)

        job.close.assert_called_once_with()
        terminate_tree.assert_not_called()

    def test_windows_timeout_closes_job_before_waiting_for_root(self) -> None:
        process = mock.Mock(spec=subprocess.Popen)
        process.wait.return_value = 1
        job = mock.Mock()

        with mock.patch.object(checks.os, "name", "nt"):
            exit_code = checks._terminate_process_tree(process, job)

        self.assertEqual(exit_code, 1)
        job.close.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=checks.PROCESS_TERMINATE_GRACE_SECONDS)
