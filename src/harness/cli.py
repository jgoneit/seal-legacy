"""Command-line interface for Outcome Harness."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from . import __version__
from .bundle import BundleError, BundleEvidenceError, create_verification_bundle
from .evidence import CompletionError, EvidenceRepositoryError, complete_task, verify_task
from .exit_codes import ExitCode
from .gitdiff import GitDiffError, GitDiffTaskError
from .task import TaskError, TaskRepositoryError, create_task, show_task
from .verdict import VerdictError, VerdictEvidenceError, record_verdict, show_verdict


def build_parser() -> argparse.ArgumentParser:
    """Build the Outcome Harness command-line parser."""
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Outcome Harness command-line interface.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    commands = parser.add_subparsers(dest="command")
    task_parser = commands.add_parser("task", help="create or inspect Task Specs")
    task_commands = task_parser.add_subparsers(dest="task_command")

    create_parser = task_commands.add_parser(
        "create", help="validate and store a Task Spec snapshot"
    )
    create_parser.add_argument("--file", required=True, help="path to a Task Spec JSON file")
    create_parser.add_argument(
        "--force", action="store_true", help="replace an existing Task snapshot"
    )

    show_parser = task_commands.add_parser("show", help="print a stored Task snapshot")
    show_parser.add_argument("task_id", metavar="TASK_ID")

    verify_parser = commands.add_parser(
        "verify", help="run Task checks and write mechanical verification evidence"
    )
    verify_parser.add_argument("task_id", metavar="TASK_ID")
    verify_parser.add_argument(
        "--base-ref",
        metavar="GIT_REF",
        help="override the Task snapshot baseline for this verification run",
    )

    verifier_parser = commands.add_parser(
        "verifier", help="record, inspect, or prepare independent verifier evidence"
    )
    verifier_commands = verifier_parser.add_subparsers(dest="verifier_command")
    record_parser = verifier_commands.add_parser(
        "record", help="validate and store a manual verifier verdict"
    )
    record_parser.add_argument("task_id", metavar="TASK_ID")
    record_parser.add_argument(
        "--run-id",
        metavar="RUN_ID",
        required=True,
        help="explicit verification run id to attach the verdict to",
    )
    record_parser.add_argument(
        "--file",
        metavar="VERDICT_JSON",
        required=True,
        help="manual verifier verdict JSON file",
    )
    verifier_show_parser = verifier_commands.add_parser(
        "show", help="print a recorded manual verifier verdict"
    )
    verifier_show_parser.add_argument("task_id", metavar="TASK_ID")
    verifier_show_parser.add_argument(
        "--run-id",
        metavar="RUN_ID",
        required=True,
        help="explicit verification run id to inspect",
    )
    bundle_parser = verifier_commands.add_parser(
        "bundle", help="export one saved Task/run as a portable verifier bundle"
    )
    bundle_parser.add_argument("task_id", metavar="TASK_ID")
    bundle_parser.add_argument(
        "--run-id",
        metavar="RUN_ID",
        required=True,
        help="explicit verification run id to export",
    )
    bundle_parser.add_argument(
        "--output",
        metavar="DIR",
        required=True,
        help="new directory to receive the verifier bundle",
    )

    complete_parser = commands.add_parser(
        "complete", help="validate saved evidence and record a Task completion"
    )
    complete_parser.add_argument("task_id", metavar="TASK_ID")
    complete_parser.add_argument(
        "--run-id",
        metavar="RUN_ID",
        required=True,
        help="explicit verification run id to validate; latest-run selection is unsupported",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = build_parser()
    arguments = parser.parse_args(argv)

    try:
        if arguments.command == "task" and arguments.task_command == "create":
            snapshot = create_task(arguments.file, force=arguments.force)
            print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
        elif arguments.command == "task" and arguments.task_command == "show":
            snapshot = show_task(arguments.task_id)
            print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
        elif arguments.command == "verify":
            run = verify_task(arguments.task_id, base_ref=arguments.base_ref)
            print(
                json.dumps(
                    {
                        "run_id": run.run_id,
                        "evidence_path": str(run.evidence_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        elif arguments.command == "verifier" and arguments.verifier_command == "record":
            record = record_verdict(
                arguments.task_id,
                arguments.run_id,
                arguments.file,
            )
            print(
                json.dumps(
                    {
                        "task_id": record.task_id,
                        "run_id": record.run_id,
                        "raw_verdict_path": str(record.raw_path),
                        "verdict_path": str(record.snapshot_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        elif arguments.command == "verifier" and arguments.verifier_command == "show":
            record = show_verdict(arguments.task_id, arguments.run_id)
            print(
                json.dumps(
                    record.verdict,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        elif arguments.command == "verifier" and arguments.verifier_command == "bundle":
            bundle = create_verification_bundle(
                arguments.task_id,
                arguments.run_id,
                arguments.output,
            )
            print(
                json.dumps(
                    {
                        "task_id": bundle.task_id,
                        "run_id": bundle.run_id,
                        "bundle_path": str(bundle.bundle_path),
                        "manifest_path": str(bundle.manifest_path),
                        "total_size_bytes": bundle.manifest["total_size_bytes"],
                        "bundle_sha256": bundle.manifest["bundle_sha256"],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        elif arguments.command == "complete":
            completion = complete_task(arguments.task_id, arguments.run_id)
            print(
                json.dumps(
                    {
                        "task_id": completion.task_id,
                        "run_id": completion.run_id,
                        "completion_path": str(completion.completion_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
    except (TaskError, GitDiffError) as error:
        print(f"error: {error}", file=sys.stderr)
        return _exit_code_for(error)
    return int(ExitCode.SUCCESS)


def _exit_code_for(error: TaskError | GitDiffError | BundleError | VerdictError) -> int:
    """Return the documented stable exit code for a handled command error."""
    if isinstance(error, CompletionError):
        return int(error.exit_code)
    if isinstance(error, BundleEvidenceError):
        return int(error.exit_code)
    if isinstance(error, VerdictEvidenceError):
        return int(ExitCode.EVIDENCE_MISSING_OR_CORRUPT)
    if isinstance(error, (TaskRepositoryError, EvidenceRepositoryError)):
        return int(ExitCode.GIT_OR_REPOSITORY_ERROR)
    if isinstance(error, GitDiffTaskError):
        return int(ExitCode.INVALID_INPUT_OR_SCHEMA)
    if isinstance(error, GitDiffError):
        return int(ExitCode.GIT_OR_REPOSITORY_ERROR)
    return int(ExitCode.INVALID_INPUT_OR_SCHEMA)
