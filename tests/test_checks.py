"""Process lifecycle coverage for verification checks."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from seal_legacy import checks


WINDOWS_OS = SimpleNamespace(name="nt")


class CheckProcessLifecycleTests(unittest.TestCase):
    """Keep platform-specific process cleanup tied to its startup ownership."""

    def test_windows_start_creates_and_assigns_the_job_before_resume(self) -> None:
        process = mock.Mock(spec=subprocess.Popen)
        job = mock.Mock()
        stdout = mock.sentinel.stdout
        stderr = mock.sentinel.stderr
        cwd = Path("/repository")
        events: list[str] = []

        def create_job() -> mock.Mock:
            events.append("create-job")
            return job

        def start_process(*_args: object, **_kwargs: object) -> mock.Mock:
            events.append("popen")
            return process

        def assign_process(actual_process: object) -> None:
            self.assertIs(actual_process, process)
            events.append("assign-job")

        def resume_process(actual_process: object) -> None:
            self.assertIs(actual_process, process)
            events.append("resume")

        job.assign_process.side_effect = assign_process

        with (
            mock.patch.object(checks, "os", WINDOWS_OS),
            mock.patch.object(
                checks.subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0x00000200,
                create=True,
            ),
            mock.patch.object(checks.subprocess, "Popen", side_effect=start_process) as popen,
            mock.patch.object(checks, "_create_windows_job", side_effect=create_job),
            mock.patch.object(checks, "_resume_windows_process", side_effect=resume_process),
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
            creationflags=0x00000200 | checks._CREATE_SUSPENDED,
        )
        self.assertEqual(events, ["create-job", "popen", "assign-job", "resume"])

    def test_windows_start_kills_suspended_root_when_job_assignment_fails(self) -> None:
        process = mock.Mock(spec=subprocess.Popen)
        process.wait.return_value = 1
        job = mock.Mock()
        job.assign_process.side_effect = OSError("job assignment failed")

        with (
            mock.patch.object(checks, "os", WINDOWS_OS),
            mock.patch.object(
                checks.subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0x00000200,
                create=True,
            ),
            mock.patch.object(checks.subprocess, "Popen", return_value=process),
            mock.patch.object(checks, "_create_windows_job", return_value=job),
            mock.patch.object(checks, "_resume_windows_process") as resume_process,
        ):
            with self.assertRaisesRegex(OSError, "job assignment failed"):
                checks._start_process(
                    ["check.exe"], Path("/repository"), mock.sentinel.stdout, mock.sentinel.stderr
                )

        job.close.assert_called_once_with()
        process.kill.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=checks.PROCESS_TERMINATE_GRACE_SECONDS)
        resume_process.assert_not_called()

    def test_windows_start_closes_assigned_job_when_resume_fails(self) -> None:
        process = mock.Mock(spec=subprocess.Popen)
        process.wait.return_value = 1
        job = mock.Mock()

        with (
            mock.patch.object(checks, "os", WINDOWS_OS),
            mock.patch.object(
                checks.subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0x00000200,
                create=True,
            ),
            mock.patch.object(checks.subprocess, "Popen", return_value=process),
            mock.patch.object(checks, "_create_windows_job", return_value=job),
            mock.patch.object(
                checks,
                "_resume_windows_process",
                side_effect=OSError("could not resume"),
            ),
        ):
            with self.assertRaisesRegex(OSError, "could not resume"):
                checks._start_process(
                    ["check.exe"], Path("/repository"), mock.sentinel.stdout, mock.sentinel.stderr
                )

        job.assign_process.assert_called_once_with(process)
        job.close.assert_called_once_with()
        process.kill.assert_not_called()
        process.wait.assert_called_once_with(timeout=checks.PROCESS_TERMINATE_GRACE_SECONDS)

    def test_windows_job_limits_allow_intentional_breakaway(self) -> None:
        self.assertEqual(
            checks._windows_job_limit_flags(),
            checks._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | checks._JOB_OBJECT_LIMIT_BREAKAWAY_OK,
        )

    def test_windows_success_cleanup_closes_job_without_taskkill(self) -> None:
        job = mock.Mock()

        with (
            mock.patch.object(checks, "os", WINDOWS_OS),
            mock.patch.object(checks, "_terminate_windows_tree") as terminate_tree,
        ):
            checks._reap_finished_process_group(mock.sentinel.process, job)

        job.close.assert_called_once_with()
        terminate_tree.assert_not_called()

    def test_windows_timeout_closes_job_before_waiting_for_root(self) -> None:
        process = mock.Mock(spec=subprocess.Popen)
        process.wait.return_value = 1
        job = mock.Mock()

        with mock.patch.object(checks, "os", WINDOWS_OS):
            exit_code = checks._terminate_process_tree(process, job)

        self.assertEqual(exit_code, 1)
        job.close.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=checks.PROCESS_TERMINATE_GRACE_SECONDS)
