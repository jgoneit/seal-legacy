"""Contract coverage for the Harness Codex Plugin skills."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPOSITORY_ROOT / "skills"
PLUGIN_MANIFEST = REPOSITORY_ROOT / ".codex-plugin" / "plugin.json"
ADAPTER_CONTRACT = REPOSITORY_ROOT / "docs" / "adapter-contract.md"
README = REPOSITORY_ROOT / "README.md"
KOREAN_README = REPOSITORY_ROOT / "README.ko.md"
EXPECTED_SKILLS = ("harness", "task", "verify", "bundle", "complete")


def _skill_text(name: str) -> str:
    return (SKILLS_ROOT / name / "SKILL.md").read_text(encoding="utf-8")


def _agent_metadata(name: str) -> str:
    return (SKILLS_ROOT / name / "agents" / "openai.yaml").read_text(
        encoding="utf-8"
    )


def _frontmatter_name(contents: str) -> str | None:
    match = re.search(r"(?m)^name:\s*([^\n]+)$", contents)
    return None if match is None else match.group(1).strip().strip('"\'')


def _normalized(contents: str) -> str:
    return " ".join(contents.split())


class PluginSkillContractTests(unittest.TestCase):
    def test_expected_skills_are_namespaced_and_resume_only_when_intended(self) -> None:
        for name in EXPECTED_SKILLS:
            with self.subTest(skill=name):
                skill_path = SKILLS_ROOT / name / "SKILL.md"
                metadata_path = SKILLS_ROOT / name / "agents" / "openai.yaml"
                self.assertTrue(skill_path.is_file())
                self.assertTrue(metadata_path.is_file())

                self.assertEqual(_frontmatter_name(_skill_text(name)), name)
                metadata = _agent_metadata(name)
                expected_policy = "true" if name == "harness" else "false"
                self.assertIn(
                    f"policy:\n  allow_implicit_invocation: {expected_policy}",
                    metadata,
                )
                invocation = "$harness" if name == "harness" else f"$harness:{name}"
                self.assertIn(invocation, metadata)

        self.assertIn(
            "unambiguous confirmation or resume reply in the same conversation",
            _normalized(_skill_text("harness")),
        )
        managed = _normalized(_skill_text("harness"))
        self.assertIn(
            "Do not treat an unrelated approval or ordinary coding request as activation",
            managed,
        )
        self.assertIn("Within an activation case above", managed)

        for name in EXPECTED_SKILLS[1:]:
            with self.subTest(explicit_follow_up=name):
                contents = _normalized(_skill_text(name))
                self.assertIn(
                    f"Ask the user to invoke `$harness:{name}` again",
                    contents,
                )
                self.assertIn(
                    "do not rely on an untagged reply",
                    contents,
                )

    def test_managed_skill_defines_one_approved_initial_verification(self) -> None:
        contents = _normalized(_skill_text("harness"))
        required_fragments = (
            "`$harness <work request>`",
            "one conversational confirmation",
            "Task creation, ordinary implementation, and the first `verify` exactly once",
            "first `verify` exactly once",
            "does not authorize `complete`",
            "restate that adopting it covers ordinary implementation, the first `verify` exactly once, and the same conditional reviewed-bundle preparation",
            "separate final confirmation immediately before `complete`",
            "same conversation",
            "successful `task create` stdout `id`",
            "successful `verify` stdout `run_id`",
            "Do not select a latest Task or Run",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, contents)

    def test_managed_skill_preserves_failure_and_review_boundaries(self) -> None:
        contents = _normalized(_skill_text("harness"))
        required_fragments = (
            "blocked or aborted",
            (
                "Do not repair source, replace Evidence, create a replacement Run, "
                "or retry verification"
            ),
            "nonzero `verify`",
            '`mechanical_result="fail"`',
            "Any nonzero Core command",
            "Do not consume partial stdout",
            "alternate output path",
            "outside the target repository",
            "verification.json",
            "mechanical_result",
            "scope_pass",
            "required_checks_pass",
            "source_stable_during_checks",
            "implementation conversation",
            "clean-context",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, contents)

    def test_task_drafts_do_not_invent_optional_check_timeouts(self) -> None:
        for name in ("harness", "task"):
            with self.subTest(skill=name):
                contents = _normalized(_skill_text(name))
                self.assertIn("catalog-derived check preview", contents)
                self.assertIn(
                    "authoritative normalized checks from successful `task create` stdout",
                    contents,
                )
                self.assertIn("`timeout_seconds` when present", contents)
                self.assertIn("do not infer a numeric default", contents)

    def test_verdict_input_does_not_mutate_verified_product_source(self) -> None:
        contents = _normalized(_skill_text("harness"))
        self.assertIn("Verdict input outside the target repository", contents)
        self.assertIn("inline Verdict JSON", contents)
        self.assertIn("Do not move or delete a repository-local Verdict", contents)
        for document in (README, KOREAN_README):
            with self.subTest(document=document.name):
                self.assertIn(
                    "<VERDICT_JSON_OUTSIDE_REPOSITORY>",
                    document.read_text(encoding="utf-8"),
                )

    def test_managed_creation_reconciles_the_approved_preview(self) -> None:
        contents = _normalized(_skill_text("harness"))
        required_fragments = (
            "saved baseline differs from the displayed HEAD",
            "saved Task fields differ from the approved draft",
            "saved checks differ from the approved preview",
            "Preserve the created Task",
            "stop before implementation or verification",
            "new explicit adoption confirmation",
            "drift re-adoption or new-Task choice",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, contents)

        self.assertIn(
            "saved Task fields, baseline, or checks",
            _normalized(README.read_text(encoding="utf-8")),
        )
        self.assertIn(
            "saved Task field, baseline, check",
            _normalized(KOREAN_README.read_text(encoding="utf-8")),
        )

    def test_readmes_separate_core_and_plugin_installation(self) -> None:
        expected = (
            (README, "does not install the Codex Plugin"),
            (KOREAN_README, "Codex Plugin을 설치하지 않습니다"),
        )
        for document, boundary in expected:
            with self.subTest(document=document.name):
                contents = document.read_text(encoding="utf-8")
                self.assertIn("### Codex Plugin", contents)
                self.assertIn("codex plugin add harness@personal", contents)
                self.assertIn(boundary, contents)

    def test_escape_hatches_name_only_their_core_operation(self) -> None:
        expected_commands = {
            "task": (
                "harness task create --file <TASK_JSON>",
                "harness task show <TASK_ID>",
            ),
            "verify": ("harness verify <TASK_ID>",),
            "bundle": (
                "harness verifier bundle <TASK_ID> --run-id <RUN_ID> --output <OUTPUT_DIR>",
            ),
            "complete": ("harness complete <TASK_ID> --run-id <RUN_ID>",),
        }
        for name, commands in expected_commands.items():
            with self.subTest(skill=name):
                contents = _skill_text(name)
                self.assertIn("Perform only the requested Core operation", contents)
                for command in commands:
                    self.assertIn(command, contents)

    def test_plugin_listing_leads_with_the_managed_workflow(self) -> None:
        manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        interface = manifest["interface"]

        self.assertIn("managed", manifest["description"].lower())
        self.assertIn("managed", interface["longDescription"].lower())
        prompts = interface["defaultPrompt"]
        self.assertLessEqual(len(prompts), 3)
        self.assertTrue(any(prompt.startswith("$harness ") for prompt in prompts))

    def test_public_docs_separate_core_and_plugin_workflows(self) -> None:
        expected = (
            (README, "## Core CLI workflow", "## Codex Plugin managed workflow"),
            (
                KOREAN_README,
                "## Core CLI workflow",
                "## Codex Plugin 관리형 workflow",
            ),
        )
        for document, core_heading, plugin_heading in expected:
            with self.subTest(document=document.name):
                contents = document.read_text(encoding="utf-8")
                self.assertIn(core_heading, contents)
                self.assertIn(plugin_heading, contents)
                for invocation in (
                    "$harness:task",
                    "$harness:verify",
                    "$harness:bundle",
                    "$harness:complete",
                ):
                    self.assertIn(invocation, contents)

        self.assertIn(
            "## Managed adapter lifecycle",
            ADAPTER_CONTRACT.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "the user's affirmative reply to the displayed covered actions",
            _normalized(README.read_text(encoding="utf-8")),
        )
        self.assertIn(
            "화면에 표시한 범위에 대한 사용자의 명확한 승인 답변",
            _normalized(KOREAN_README.read_text(encoding="utf-8")),
        )


if __name__ == "__main__":
    unittest.main()
