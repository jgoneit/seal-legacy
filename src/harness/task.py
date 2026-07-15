"""Task Spec parsing, validation, and snapshot storage."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


TASK_SCHEMA_VERSION = 1
TASK_TYPES = frozenset({"bugfix", "feature", "refactor", "test", "docs", "config-infra"})
TASK_RISKS = frozenset({"low", "medium", "high"})
TASK_ID_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)


class TaskError(ValueError):
    """Base error for Task Spec operations."""


class TaskValidationError(TaskError):
    """Raised when a Task Spec or check catalog is invalid."""


class TaskRepositoryError(TaskError):
    """Raised when the current directory is not an initialized Git repository."""


class TaskAlreadyExistsError(TaskError):
    """Raised when saving a task would replace an existing snapshot."""


class TaskNotFoundError(TaskError):
    """Raised when a requested Task snapshot is not present."""


def create_task(
    task_file: str | Path,
    *,
    cwd: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Validate a Task Spec and write its normalized snapshot into the repository."""
    repository = find_repository_root(cwd)
    task_spec = _load_json_object(Path(task_file), "Task Spec")
    catalog = load_check_catalog(repository)
    snapshot = normalize_task_spec(task_spec, catalog)
    snapshot["baseline"] = current_head(repository)
    save_task_snapshot(repository, snapshot, force=force)
    return snapshot


def show_task(task_id: str, *, cwd: str | Path | None = None) -> dict[str, Any]:
    """Load a stored Task snapshot by id from the current repository."""
    validate_task_id(task_id)
    repository = find_repository_root(cwd)
    task_path = _task_path(repository, task_id)
    if not task_path.is_file():
        raise TaskNotFoundError(f"Task '{task_id}' does not exist.")
    return _load_json_object(task_path, f"Task snapshot '{task_id}'")


def normalize_task_spec(
    task_spec: object,
    check_catalog: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate a Task Spec and return its portable, normalized representation."""
    spec = _require_object(task_spec, "Task Spec")
    _require_exact_keys(
        spec,
        required={
            "schema_version",
            "id",
            "type",
            "objective",
            "scope",
            "checks",
            "risk",
            "verifier",
        },
        context="Task Spec",
    )

    schema_version = spec["schema_version"]
    if type(schema_version) is not int or schema_version != TASK_SCHEMA_VERSION:
        raise TaskValidationError(
            f"Task Spec schema_version must be {TASK_SCHEMA_VERSION}."
        )

    task_id = spec["id"]
    validate_task_id(task_id)

    task_type = spec["type"]
    if not isinstance(task_type, str) or task_type not in TASK_TYPES:
        allowed = ", ".join(sorted(TASK_TYPES))
        raise TaskValidationError(f"Task Spec type must be one of: {allowed}.")

    objective = _require_nonempty_string(spec["objective"], "Task Spec objective")

    risk = spec["risk"]
    if not isinstance(risk, str) or risk not in TASK_RISKS:
        allowed = ", ".join(sorted(TASK_RISKS))
        raise TaskValidationError(f"Task Spec risk must be one of: {allowed}.")

    scope = _normalize_scope(spec["scope"])
    checks = _normalize_checks(spec["checks"], check_catalog)
    verifier = _normalize_verifier(spec["verifier"])

    return {
        "schema_version": TASK_SCHEMA_VERSION,
        "id": task_id,
        "type": task_type,
        "objective": objective,
        "scope": scope,
        "checks": checks,
        "risk": risk,
        "verifier": verifier,
    }


def load_check_catalog(repository: str | Path) -> dict[str, dict[str, Any]]:
    """Load and validate the repository-level check catalog."""
    catalog_path = Path(repository) / ".harness" / "checks.json"
    if not catalog_path.is_file():
        raise TaskValidationError(
            f"Check catalog is missing: {catalog_path.relative_to(repository)}."
        )

    catalog = _load_json_object(catalog_path, "Check catalog")
    allowed_keys = {"schema_version", "checks"}
    unexpected_keys = set(catalog) - allowed_keys
    if unexpected_keys:
        names = ", ".join(sorted(unexpected_keys))
        raise TaskValidationError(f"Check catalog has unexpected field(s): {names}.")

    if "schema_version" in catalog:
        version = catalog["schema_version"]
        if type(version) is not int or version != TASK_SCHEMA_VERSION:
            raise TaskValidationError(
                f"Check catalog schema_version must be {TASK_SCHEMA_VERSION}."
            )

    if "checks" not in catalog:
        raise TaskValidationError("Check catalog is missing required field: checks.")

    entries = catalog["checks"]
    if isinstance(entries, list):
        definitions = entries
    elif isinstance(entries, Mapping):
        definitions = []
        for name, definition in entries.items():
            if not isinstance(name, str):
                raise TaskValidationError("Check catalog names must be strings.")
            definition_object = _require_object(definition, f"Check catalog entry '{name}'")
            if "name" in definition_object and definition_object["name"] != name:
                raise TaskValidationError(
                    f"Check catalog entry '{name}' has a different name field."
                )
            definitions.append({"name": name, **definition_object})
    else:
        raise TaskValidationError("Check catalog checks must be an array or object.")

    resolved: dict[str, dict[str, Any]] = {}
    for index, definition in enumerate(definitions):
        normalized = _normalize_check_definition(definition, f"Check catalog checks[{index}]")
        name = normalized["name"]
        if name in resolved:
            raise TaskValidationError(f"Check catalog defines '{name}' more than once.")
        resolved[name] = normalized
    return resolved


def save_task_snapshot(
    repository: str | Path,
    snapshot: Mapping[str, Any],
    *,
    force: bool = False,
) -> Path:
    """Persist a normalized Task snapshot without replacing it by default."""
    task_id = snapshot.get("id")
    validate_task_id(task_id)
    task_path = _task_path(Path(repository), task_id)
    task_path.parent.mkdir(parents=True, exist_ok=True)
    contents = _format_json(snapshot)

    if force:
        task_path.write_text(contents, encoding="utf-8")
        return task_path

    try:
        with task_path.open("x", encoding="utf-8") as output:
            output.write(contents)
    except FileExistsError as error:
        raise TaskAlreadyExistsError(
            f"Task '{task_id}' already exists; use --force to replace it."
        ) from error
    return task_path


def find_repository_root(cwd: str | Path | None = None) -> Path:
    """Return the Git top-level directory for *cwd*."""
    working_directory = Path.cwd() if cwd is None else Path(cwd)
    try:
        result = subprocess.run(
            ["git", "-C", str(working_directory), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise TaskRepositoryError("Git is required to create or show a task.") from error

    if result.returncode != 0 or not result.stdout.strip():
        raise TaskRepositoryError("Task commands must run inside a Git repository.")
    return Path(result.stdout.strip()).resolve()


def current_head(repository: str | Path) -> str:
    """Read the current Git HEAD commit for snapshot baseline metadata."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise TaskRepositoryError("Git is required to record a task baseline.") from error

    if result.returncode != 0 or not result.stdout.strip():
        raise TaskRepositoryError("Task creation requires a repository with a current HEAD.")
    return result.stdout.strip()


def validate_task_id(task_id: object) -> str:
    """Validate a task identifier before using it in a snapshot path."""
    if not isinstance(task_id, str) or not task_id:
        raise TaskValidationError("Task id must be a non-empty string.")
    if task_id[0] not in TASK_ID_CHARACTERS - {"_", "-"}:
        raise TaskValidationError(
            "Task id must begin with an alphanumeric character and contain only "
            "letters, numbers, underscores, or hyphens."
        )
    if any(character not in TASK_ID_CHARACTERS for character in task_id):
        raise TaskValidationError(
            "Task id must contain only letters, numbers, underscores, or hyphens."
        )
    return task_id


def _normalize_scope(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise TaskValidationError("Task Spec scope must be a non-empty array.")
    return [_normalize_scope_path(path, index) for index, path in enumerate(value)]


def _normalize_scope_path(value: object, index: int) -> str:
    context = f"Task Spec scope[{index}]"
    path = _require_nonempty_string(value, context)
    portable_path = path.replace("\\", "/")
    windows_path = PureWindowsPath(path)

    if (
        PurePosixPath(portable_path).is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
    ):
        raise TaskValidationError(f"{context} must be relative to the repository root.")

    parts = portable_path.split("/")
    if ".." in parts:
        raise TaskValidationError(f"{context} must not contain '..' traversal.")

    normalized_parts = [part for part in parts if part not in {"", "."}]
    return "." if not normalized_parts else "/".join(normalized_parts)


def _normalize_checks(
    value: object,
    check_catalog: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise TaskValidationError("Task Spec checks must be a non-empty array.")

    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(value):
        context = f"Task Spec checks[{index}]"
        if isinstance(entry, str):
            _require_nonempty_string(entry, context)
            try:
                catalog_definition = check_catalog[entry]
            except KeyError as error:
                raise TaskValidationError(
                    f"{context} references unknown catalog check '{entry}'."
                ) from error
            normalized.append(
                _normalize_check_definition(catalog_definition, f"{context} catalog definition")
            )
        else:
            normalized.append(_normalize_check_definition(entry, context))
    return normalized


def _normalize_check_definition(value: object, context: str) -> dict[str, Any]:
    definition = _require_object(value, context)
    _require_exact_keys(
        definition,
        required={"name", "argv", "required"},
        optional={"timeout_seconds"},
        context=context,
    )

    name = _require_nonempty_string(definition["name"], f"{context} name")
    argv = definition["argv"]
    if not isinstance(argv, list) or not argv:
        raise TaskValidationError(f"{context} argv must be a non-empty array.")
    normalized_argv = [
        _require_nonempty_string(argument, f"{context} argv[{index}]")
        for index, argument in enumerate(argv)
    ]

    required = definition["required"]
    if type(required) is not bool:
        raise TaskValidationError(f"{context} required must be a boolean.")

    normalized: dict[str, Any] = {
        "name": name,
        "argv": normalized_argv,
        "required": required,
    }
    if "timeout_seconds" in definition:
        timeout_seconds = definition["timeout_seconds"]
        if type(timeout_seconds) is not int or timeout_seconds <= 0:
            raise TaskValidationError(
                f"{context} timeout_seconds must be a positive integer."
            )
        normalized["timeout_seconds"] = timeout_seconds
    return normalized


def _normalize_verifier(value: object) -> dict[str, Any]:
    verifier = _require_object(value, "Task Spec verifier")
    _require_exact_keys(
        verifier,
        required={"required"},
        optional={"preferred_runner"},
        context="Task Spec verifier",
    )
    required = verifier["required"]
    if type(required) is not bool:
        raise TaskValidationError("Task Spec verifier required must be a boolean.")

    normalized: dict[str, Any] = {"required": required}
    if "preferred_runner" in verifier:
        normalized["preferred_runner"] = _require_nonempty_string(
            verifier["preferred_runner"], "Task Spec verifier preferred_runner"
        )
    return normalized


def _require_object(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TaskValidationError(f"{context} must be a JSON object.")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    context: str,
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    missing = required - set(value)
    if missing:
        names = ", ".join(sorted(missing))
        raise TaskValidationError(f"{context} is missing required field(s): {names}.")
    unexpected = set(value) - required - optional
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise TaskValidationError(f"{context} has unexpected field(s): {names}.")


def _require_nonempty_string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise TaskValidationError(f"{context} must be a non-empty string.")
    return value


def _task_path(repository: Path, task_id: str) -> Path:
    return repository / ".harness" / "tasks" / f"{task_id}.json"


def _load_json_object(path: Path, context: str) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as source:
            value = json.load(source)
    except FileNotFoundError as error:
        raise TaskValidationError(f"{context} file does not exist: {path}.") from error
    except json.JSONDecodeError as error:
        raise TaskValidationError(f"{context} is not valid JSON: {error.msg}.") from error
    except OSError as error:
        raise TaskValidationError(f"Could not read {context}: {path}.") from error

    object_value = _require_object(value, context)
    return dict(object_value)


def _format_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
