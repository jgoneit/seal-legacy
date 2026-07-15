"""Command-line interface for Outcome Harness."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from . import __version__
from .task import TaskError, create_task, show_task


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
    except TaskError as error:
        parser.error(str(error))
    return 0
