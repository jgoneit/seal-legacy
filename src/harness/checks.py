"""Safe, ordered execution of Task Spec checks.

Each check is launched directly from its argv array.  Output is streamed to
per-check evidence files so a large stdout/stderr stream is never retained in
memory by the verifier.
"""

from __future__ import annotations

import hashlib
import os
import re
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CHECK_TIMEOUT_SECONDS = 300
PROCESS_TERMINATE_GRACE_SECONDS = 0.2


class CheckExecutionError(ValueError):
    """Raised when a check definition cannot be executed safely."""


def run_checks(
    checks: Sequence[Mapping[str, object]],
    *,
    cwd: str | Path,
    evidence_directory: str | Path,
    default_timeout_seconds: int = DEFAULT_CHECK_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Run *checks* in order and return JSON-serializable result records.

    ``cwd`` is the repository root for every check.  The result paths are
    relative to ``evidence_directory`` so an evidence bundle stays portable.
    Checks keep running after a failure in order to preserve evidence for the
    complete Task Spec.
    """
    if type(default_timeout_seconds) is not int or default_timeout_seconds <= 0:
        raise CheckExecutionError("The default check timeout must be a positive integer.")

    working_directory = Path(cwd).resolve()
    evidence_root = Path(evidence_directory).resolve()
    output_directory = evidence_root / "checks"
    output_directory.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for index, check in enumerate(checks):
        name = _required_string(check.get("name"), f"checks[{index}].name")
        argv = _argv(check.get("argv"), index)
        required = _required_boolean(check.get("required"), f"checks[{index}].required")
        timeout = _effective_timeout(check, index, default_timeout_seconds)
        stem = _output_stem(index, name)
        stdout_path = output_directory / f"{stem}.stdout"
        stderr_path = output_directory / f"{stem}.stderr"

        results.append(
            _run_one_check(
                name=name,
                argv=argv,
                required=required,
                timeout=timeout,
                cwd=working_directory,
                evidence_root=evidence_root,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        )
    return results


def _run_one_check(
    *,
    name: str,
    argv: list[str],
    required: bool,
    timeout: int,
    cwd: Path,
    evidence_root: Path,
    stdout_path: Path,
    stderr_path: Path,
) -> dict[str, Any]:
    started_at = _utc_timestamp()
    started = time.monotonic()
    timed_out = False
    exit_code: int | None = None

    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process: subprocess.Popen[bytes] | None = None
        try:
            process = _start_process(argv, cwd, stdout, stderr)
            try:
                exit_code = process.wait(timeout=timeout)
                _reap_finished_process_group(process)
            except subprocess.TimeoutExpired:
                timed_out = True
                exit_code = _terminate_process_tree(process)
        except OSError as error:
            # A missing executable is a failed check with inspectable evidence,
            # rather than a verifier crash that loses later check results.
            stderr.write(f"Could not start check: {error}\n".encode("utf-8", "replace"))
        except BaseException:
            if process is not None:
                _terminate_process_tree(process)
            raise

    finished_at = _utc_timestamp()
    duration_seconds = max(0.0, time.monotonic() - started)
    passed = not timed_out and exit_code == 0
    return {
        "name": name,
        "argv": argv,
        "cwd": str(cwd),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
        "effective_timeout": timeout,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout_path": stdout_path.relative_to(evidence_root).as_posix(),
        "stderr_path": stderr_path.relative_to(evidence_root).as_posix(),
        "required": required,
        "passed": passed,
    }


def _start_process(
    argv: list[str],
    cwd: Path,
    stdout: Any,
    stderr: Any,
) -> subprocess.Popen[bytes]:
    """Start one check in its own process group without a shell."""
    options: dict[str, Any] = {
        "cwd": str(cwd),
        "stdout": stdout,
        "stderr": stderr,
        "shell": False,
    }
    if os.name == "posix":
        options["start_new_session"] = True
    elif os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(argv, **options)


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> int | None:
    """Terminate a timed-out process and its descendants, then reap it."""
    if os.name == "posix":
        # ``start_new_session`` makes this process its own process-group leader.
        # Addressing the recorded pid keeps working even after the parent exits
        # while a child still owns the process group.
        _signal_process_group(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=PROCESS_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        # Send SIGKILL even when the parent already exited: a child may have
        # ignored SIGTERM and must not outlive the timed-out check.
        _signal_process_group(process.pid, signal.SIGKILL)
    elif os.name == "nt":
        _terminate_windows_tree(process)
    else:
        process.terminate()

    try:
        return process.wait(timeout=PROCESS_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait()


def _reap_finished_process_group(process: subprocess.Popen[bytes]) -> None:
    """Stop background descendants after a successful parent check exits."""
    if os.name == "posix":
        # The parent has already been reaped, but start_new_session keeps any
        # background descendants in its process group.  Ensure they cannot
        # keep writing to finalized Evidence Run logs.
        _signal_process_group(process.pid, signal.SIGTERM)
        _signal_process_group(process.pid, signal.SIGKILL)
    elif os.name == "nt":
        _terminate_windows_tree(process)


def _signal_process_group(process_group_id: int, signal_number: signal.Signals) -> None:
    try:
        os.killpg(process_group_id, signal_number)
    except ProcessLookupError:
        # Every process in the group exited between poll/wait and the signal.
        pass


def _terminate_windows_tree(process: subprocess.Popen[bytes]) -> None:
    """Use taskkill's tree mode where Windows provides it, without a shell."""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except OSError:
        # Keep a best-effort fallback when taskkill is absent from the runtime.
        process.kill()


def _effective_timeout(check: Mapping[str, object], index: int, default: int) -> int:
    timeout = check.get("timeout_seconds", default)
    if type(timeout) is not int or timeout <= 0:
        raise CheckExecutionError(f"checks[{index}].timeout_seconds must be a positive integer.")
    return timeout


def _required_string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise CheckExecutionError(f"{context} must be a non-empty string.")
    return value


def _required_boolean(value: object, context: str) -> bool:
    if type(value) is not bool:
        raise CheckExecutionError(f"{context} must be a boolean.")
    return value


def _argv(value: object, index: int) -> list[str]:
    if not isinstance(value, list) or not value:
        raise CheckExecutionError(f"checks[{index}].argv must be a non-empty array.")
    return [_required_string(argument, f"checks[{index}].argv[{position}]") for position, argument in enumerate(value)]


def _output_stem(index: int, name: str) -> str:
    """Create a deterministic, traversal-safe filename component for a check."""
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._-") or "check"
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    return f"{index:03d}-{slug[:48]}-{digest}"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
