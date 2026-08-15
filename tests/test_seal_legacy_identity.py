"""Regression coverage for the current Seal Legacy Core (Python) identity."""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPOSITORY_ROOT / "pyproject.toml"
CURRENT_IDENTITY_ROOTS = (
    REPOSITORY_ROOT / ".codex-plugin",
    REPOSITORY_ROOT / "docs" / "adapter-contract.md",
    REPOSITORY_ROOT / "docs" / "architecture.md",
    REPOSITORY_ROOT / "docs" / "credential-boundary.md",
    REPOSITORY_ROOT / "docs" / "exit-codes.md",
    REPOSITORY_ROOT / "docs" / "seal-legacy-ui-smoke.md",
    *(REPOSITORY_ROOT / "docs" / "adr" / f"000{number}-{slug}.md" for number, slug in (
        (1, "canonical-verdict-contract"),
        (2, "run-integrity-vs-completion-policy"),
        (3, "run-evidence-manifest"),
        (4, "canonical-source-snapshot"),
        (5, "verify-complete-source-binding"),
    )),
    REPOSITORY_ROOT / "prompts",
    REPOSITORY_ROOT / "schemas",
    REPOSITORY_ROOT / "scripts",
    REPOSITORY_ROOT / "skills",
    REPOSITORY_ROOT / "src" / "seal_legacy",
)


class SealLegacyIdentityTests(unittest.TestCase):
    """Keep current development surfaces on one Seal Legacy identity."""

    def test_python_distribution_package_and_cli_are_seal_legacy(self) -> None:
        pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

        self.assertEqual(pyproject["project"]["name"], "seal-legacy-core")
        self.assertEqual(
            pyproject["project"]["scripts"],
            {"seal-legacy": "seal_legacy.cli:main"},
        )
        self.assertEqual(
            pyproject["tool"]["setuptools"]["package-data"],
            {"seal_legacy": ["resources/*.md", "resources/*.json"]},
        )
        self.assertEqual(
            pyproject["tool"]["setuptools"]["dynamic"]["version"],
            {"attr": "seal_legacy.__version__"},
        )
        self.assertTrue((REPOSITORY_ROOT / "src" / "seal_legacy").is_dir())
        self.assertFalse((REPOSITORY_ROOT / "src" / "seal").exists())
        self.assertFalse((REPOSITORY_ROOT / "src" / "harness").exists())

    def test_repository_metadata_root_is_seal(self) -> None:
        self.assertTrue((REPOSITORY_ROOT / ".seal" / "checks.json").is_file())
        self.assertFalse(
            (REPOSITORY_ROOT / ".harness" / "checks.json").exists()
        )
        readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
        korean_readme = (REPOSITORY_ROOT / "README.ko.md").read_text(
            encoding="utf-8"
        )
        for contents in (readme, korean_readme):
            self.assertIn("`.seal`", contents)
            self.assertIn("`.harness`", contents)
        self.assertIn("does not read or migrate", readme)
        self.assertIn("읽거나 이전하지 않으므로", korean_readme)

    def test_current_source_surfaces_do_not_retain_harness_identity(self) -> None:
        forbidden = (
            "Outcome Harness",
            "outcome-harness",
            "outcome_harness",
            "Harness",
            "harness",
            ".harness",
        )

        for root in CURRENT_IDENTITY_ROOTS:
            paths = (root,) if root.is_file() else tuple(
                path
                for path in root.rglob("*")
                if path.is_file()
                and path.suffix in {".json", ".md", ".py", ".toml", ".yaml", ".yml"}
            )
            for path in paths:
                contents = path.read_text(encoding="utf-8")
                for phrase in forbidden:
                    with self.subTest(
                        path=path.relative_to(REPOSITORY_ROOT),
                        phrase=phrase,
                    ):
                        self.assertNotIn(phrase, contents)

    def test_current_ci_rejects_retired_import_names(self) -> None:
        ci = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("find_spec('seal') is None", ci)
        self.assertIn("find_spec('harness') is None", ci)


if __name__ == "__main__":
    unittest.main()
