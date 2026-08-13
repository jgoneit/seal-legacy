"""Static consistency checks for Core development and release surfaces."""

from __future__ import annotations

import json
import re
import sys
import tomllib
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from harness import __version__
from harness.checks import DEFAULT_CHECK_TIMEOUT_SECONDS


PYPROJECT = REPOSITORY_ROOT / "pyproject.toml"
SDIST_MANIFEST = REPOSITORY_ROOT / "MANIFEST.in"
PLUGIN_MANIFEST = REPOSITORY_ROOT / ".codex-plugin" / "plugin.json"
CHECK_CATALOG = REPOSITORY_ROOT / ".harness" / "checks.json"
CI_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
SKILL_NAMES = ("seal", "task", "verify", "bundle", "complete")
SKILLS = tuple(
    REPOSITORY_ROOT / "skills" / name / "SKILL.md" for name in SKILL_NAMES
)
README = REPOSITORY_ROOT / "README.md"
KOREAN_README = REPOSITORY_ROOT / "README.ko.md"
CURRENT_CONTRACT_DOCS = (
    README,
    KOREAN_README,
    REPOSITORY_ROOT / "docs" / "architecture.md",
    REPOSITORY_ROOT / "docs" / "adapter-contract.md",
    REPOSITORY_ROOT / "docs" / "exit-codes.md",
    REPOSITORY_ROOT / "docs" / "migration-v0.2.md",
)
CORE_DEVELOPMENT_VERSION = "0.3.0.dev0"
PLUGIN_DEVELOPMENT_VERSION = "0.3.0-dev.0"
PUBLISHED_RELEASE_VERSION = "0.2.1"


class ReleaseContractTests(unittest.TestCase):
    """Keep Core development and published release identities explicit."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        cls.plugin_manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        cls.check_catalog = json.loads(CHECK_CATALOG.read_text(encoding="utf-8"))
        cls.ci_workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        cls.workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
        cls.skills = {
            path.parent.name: path.read_text(encoding="utf-8") for path in SKILLS
        }
        cls.readme = README.read_text(encoding="utf-8")
        cls.korean_readme = KOREAN_README.read_text(encoding="utf-8")

    def test_core_plugin_development_and_published_versions_are_explicit(self) -> None:
        self.assertEqual(__version__, CORE_DEVELOPMENT_VERSION)
        self.assertEqual(
            self.plugin_manifest["version"],
            PLUGIN_DEVELOPMENT_VERSION,
        )
        self.assertRegex(
            PLUGIN_DEVELOPMENT_VERSION,
            r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)-"
            r"(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*)"
            r"(?:\.(?:0|[1-9]\d*|[A-Za-z-][0-9A-Za-z-]*))*$",
        )
        self.assertNotEqual(
            PLUGIN_DEVELOPMENT_VERSION,
            PUBLISHED_RELEASE_VERSION,
        )
        self.assertIn("version", self.pyproject["project"]["dynamic"])
        self.assertEqual(
            self.pyproject["tool"]["setuptools"]["dynamic"]["version"],
            {"attr": "harness.__version__"},
        )

    def test_release_workflow_matches_distribution_and_version(self) -> None:
        distribution = self.pyproject["project"]["name"].replace("-", "_")
        artifact_stem = f"{distribution}-{PUBLISHED_RELEASE_VERSION}"
        expected_note = f"docs/releases/v{PUBLISHED_RELEASE_VERSION}.md"

        self.assertIn(f'- "v{PUBLISHED_RELEASE_VERSION}"', self.workflow)
        self.assertIn(
            f"dist/{artifact_stem}-*.whl",
            self.workflow,
        )
        self.assertIn(
            f"dist/{artifact_stem}-py3-none-any.whl",
            self.workflow,
        )
        self.assertIn(f"dist/{artifact_stem}.tar.gz", self.workflow)
        self.assertIn(
            f"name: Harness v{PUBLISHED_RELEASE_VERSION} (Experimental)",
            self.workflow,
        )
        self.assertIn(f"body_path: {expected_note}", self.workflow)
        self.assertTrue((REPOSITORY_ROOT / expected_note).is_file())

    def test_release_workflow_keeps_required_validation_gates(self) -> None:
        required_fragments = (
            "python scripts/sync_contracts.py --check",
            "python -m unittest discover -s tests -v",
            "python -m build",
            "python -m twine check dist/*",
            "verdict.schema.json",
            "verifier.md",
            "fail_on_unmatched_files: true",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.workflow)

    def test_self_host_unit_test_timeout_matches_core_default(self) -> None:
        unit_test_checks = [
            check
            for check in self.check_catalog["checks"]
            if check["name"] == "unit-test"
        ]
        self.assertEqual(len(unit_test_checks), 1)
        self.assertEqual(
            unit_test_checks[0]["timeout_seconds"],
            DEFAULT_CHECK_TIMEOUT_SECONDS,
        )

    def test_clean_wheel_workflows_require_their_exact_cli_version(self) -> None:
        expected_assertions = (
            (
                self.ci_workflow,
                'test "$("$RUNNER_TEMP/clean-install/bin/harness" --version)" '
                f'= "{CORE_DEVELOPMENT_VERSION}"',
            ),
            (
                self.workflow,
                'test "$("$RUNNER_TEMP/outcome-harness-clean/bin/harness" '
                '--version)" = "0.2.1"',
            ),
        )
        for workflow, assertion in expected_assertions:
            with self.subTest(assertion=assertion):
                self.assertIn(assertion, workflow)

    def test_sdist_manifest_excludes_repository_test_suite(self) -> None:
        self.assertTrue(SDIST_MANIFEST.is_file())
        directives = {
            line.strip()
            for line in SDIST_MANIFEST.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertIn("prune tests", directives)

    def test_readme_pair_matches_current_release_and_install_artifacts(self) -> None:
        english_claim = re.search(
            r"The latest Outcome Harness Core Experimental release is `v([^`]+)`",
            self.readme,
        )
        korean_claim = re.search(
            r"최신 Outcome Harness Core Experimental release는 `v([^`]+)`",
            self.korean_readme,
        )
        self.assertIsNotNone(english_claim)
        self.assertIsNotNone(korean_claim)
        self.assertEqual(english_claim.group(1), PUBLISHED_RELEASE_VERSION)
        self.assertEqual(korean_claim.group(1), PUBLISHED_RELEASE_VERSION)

        install_ref = (
            "git+https://github.com/jgoneit/seal.git@"
            f"v{PUBLISHED_RELEASE_VERSION}"
        )
        distribution = self.pyproject["project"]["name"].replace("-", "_")
        wheel_name = (
            f"{distribution}-{PUBLISHED_RELEASE_VERSION}-py3-none-any.whl"
        )
        for document in (self.readme, self.korean_readme):
            self.assertIn(install_ref, document)
            self.assertIn(wheel_name, document)

    def test_skills_support_only_the_core_v0_3_development_range(self) -> None:
        for name, contents in self.skills.items():
            with self.subTest(skill=name):
                self.assertIn("`>=0.3.0.dev0,<0.4.0`", contents)
                self.assertNotIn("`>=0.2.0,<0.3.0`", contents)
                self.assertNotIn(">=0.1.0", contents)
                self.assertNotIn("v0.1.1", contents)
                self.assertNotIn("git+https://", contents)
                self.assertNotRegex(
                    contents,
                    r"(?m)^\s*(?:from|import)\s+harness",
                )

    def test_current_contract_docs_do_not_retain_retired_release_dev_version(self) -> None:
        retired_development_version = f"{PUBLISHED_RELEASE_VERSION}.dev0"
        for document in CURRENT_CONTRACT_DOCS:
            with self.subTest(document=document.relative_to(REPOSITORY_ROOT)):
                self.assertNotIn(
                    retired_development_version,
                    document.read_text(encoding="utf-8"),
                )


if __name__ == "__main__":
    unittest.main()
