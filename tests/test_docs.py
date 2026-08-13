from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPOSITORY_ROOT / "docs"
README = REPOSITORY_ROOT / "README.md"
KOREAN_README = REPOSITORY_ROOT / "README.ko.md"
SKILL = REPOSITORY_ROOT / "skills" / "harness" / "SKILL.md"
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def _public_documents() -> tuple[Path, ...]:
    return (
        README,
        KOREAN_README,
        *sorted(DOCS_ROOT.rglob("*.md")),
    )


def _local_link_targets(document: Path) -> list[Path]:
    targets: list[Path] = []
    for match in MARKDOWN_LINK.finditer(document.read_text(encoding="utf-8")):
        raw_target = match.group(1).strip()
        if raw_target.startswith(("#", "http://", "https://", "mailto:")):
            continue

        target_without_title = raw_target.split(maxsplit=1)[0].strip("<>")
        path_text = unquote(target_without_title.split("#", 1)[0])
        if path_text:
            targets.append((document.parent / path_text).resolve())
    return targets


class PublicDocumentationTest(unittest.TestCase):
    def test_readme_language_selectors_are_reciprocal(self) -> None:
        english_lines = README.read_text(encoding="utf-8").splitlines()
        korean_lines = KOREAN_README.read_text(encoding="utf-8").splitlines()

        self.assertEqual(english_lines[:3], [
            "# Harness",
            "",
            "Language: English | [한국어](README.ko.md)",
        ])
        self.assertEqual(korean_lines[:3], [
            "# Harness",
            "",
            "Language: [English](README.md) | 한국어",
        ])

    def test_technical_docs_are_canonical_english(self) -> None:
        self.assertEqual(list(DOCS_ROOT.rglob("*.ko.md")), [])
        for document in DOCS_ROOT.rglob("*.md"):
            with self.subTest(document=document.relative_to(REPOSITORY_ROOT)):
                self.assertNotIn(
                    "Language:",
                    document.read_text(encoding="utf-8"),
                )

    def test_all_local_markdown_links_resolve(self) -> None:
        for document in _public_documents():
            for target in _local_link_targets(document):
                with self.subTest(
                    document=document.relative_to(REPOSITORY_ROOT),
                    target=target,
                ):
                    self.assertTrue(target.is_relative_to(REPOSITORY_ROOT))
                    self.assertTrue(target.exists())

    def test_historical_release_notes_remain_available_in_english(self) -> None:
        self.assertTrue((DOCS_ROOT / "releases" / "v0.1.0.md").is_file())
        self.assertTrue((DOCS_ROOT / "releases" / "v0.1.1.md").is_file())

    def test_current_contract_docs_do_not_claim_v1_compatibility(self) -> None:
        current_documents = (
            README,
            KOREAN_README,
            DOCS_ROOT / "architecture.md",
            DOCS_ROOT / "adapter-contract.md",
            DOCS_ROOT / "exit-codes.md",
        )
        forbidden = (
            "Legacy verification v1",
            "legacy v1",
            "v1 Run remains",
            "v0.1.1 fallback",
            "legacy behavior profile",
        )
        for document in current_documents:
            contents = document.read_text(encoding="utf-8")
            for phrase in forbidden:
                with self.subTest(
                    document=document.relative_to(REPOSITORY_ROOT),
                    phrase=phrase,
                ):
                    self.assertNotIn(phrase, contents)

    def test_skill_supports_only_the_v0_2_release_profile(self) -> None:
        contents = SKILL.read_text(encoding="utf-8")

        self.assertIn("`>=0.2.0,<0.3.0`", contents)
        self.assertNotIn(">=0.1.0", contents)
        self.assertNotIn("v0.1.1", contents)
        self.assertNotIn("git+https://", contents)
        self.assertNotRegex(contents, r"(?m)^\s*(?:from|import)\s+harness")

    def test_v0_3_validated_run_summary_contract_is_documented(self) -> None:
        adapter_contract = (DOCS_ROOT / "adapter-contract.md").read_text(
            encoding="utf-8"
        )
        architecture = (DOCS_ROOT / "architecture.md").read_text(encoding="utf-8")
        exit_codes = (DOCS_ROOT / "exit-codes.md").read_text(encoding="utf-8")

        for contents in (
            README.read_text(encoding="utf-8"),
            KOREAN_README.read_text(encoding="utf-8"),
        ):
            self.assertIn("harness run show TASK-001 --run-id <RUN_ID>", contents)
            self.assertIn("validated-run-summary/v1", contents)

        self.assertIn(
            "harness run show <TASK_ID> --run-id <RUN_ID>",
            adapter_contract,
        )
        self.assertIn("validated-run-summary/v1", adapter_contract)
        self.assertIn("calls `validate_run()` once", architecture)
        self.assertIn(
            "does not return exits 4–7 or 9",
            " ".join(exit_codes.split()),
        )
        self.assertIn('"schema_version": 1', adapter_contract)


if __name__ == "__main__":
    unittest.main()
