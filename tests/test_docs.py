from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPOSITORY_ROOT / "docs"
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def _english_documents() -> tuple[Path, ...]:
    docs = sorted(
        path
        for path in DOCS_ROOT.rglob("*.md")
        if not path.name.endswith(".ko.md")
    )
    return (REPOSITORY_ROOT / "README.md", *docs)


def _korean_path(english_path: Path) -> Path:
    return english_path.with_name(f"{english_path.stem}.ko.md")


def _local_link_targets(document: Path) -> list[Path]:
    targets: list[Path] = []
    for match in MARKDOWN_LINK.finditer(document.read_text(encoding="utf-8")):
        raw_target = match.group(1).strip()
        if raw_target.startswith(("#", "http://", "https://", "mailto:")):
            continue

        target_without_title = raw_target.split(maxsplit=1)[0].strip("<>")
        path_text = unquote(target_without_title.split("#", 1)[0])
        if not path_text:
            continue

        targets.append((document.parent / path_text).resolve())
    return targets


class PublicDocumentationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.english_documents = _english_documents()
        self.expected_korean_documents = {
            _korean_path(document) for document in self.english_documents
        }
        self.all_public_documents = {
            *self.english_documents,
            *self.expected_korean_documents,
        }

    def test_every_public_document_has_exactly_one_language_pair(self) -> None:
        actual_korean_documents = {
            REPOSITORY_ROOT / "README.ko.md",
            *DOCS_ROOT.rglob("*.ko.md"),
        }

        self.assertEqual(actual_korean_documents, self.expected_korean_documents)
        for document in self.all_public_documents:
            with self.subTest(document=document.relative_to(REPOSITORY_ROOT)):
                self.assertTrue(document.is_file())

    def test_language_selectors_are_reciprocal_and_below_the_title(self) -> None:
        for english_document in self.english_documents:
            korean_document = _korean_path(english_document)
            english_lines = english_document.read_text(encoding="utf-8").splitlines()
            korean_lines = korean_document.read_text(encoding="utf-8").splitlines()
            english_selector = (
                f"Language: English | [한국어]({korean_document.name})"
            )
            korean_selector = (
                f"Language: [English]({english_document.name}) | 한국어"
            )

            with self.subTest(document=english_document.relative_to(REPOSITORY_ROOT)):
                self.assertTrue(english_lines[0].startswith("# "))
                self.assertEqual(english_lines[1], "")
                self.assertEqual(english_lines[2], english_selector)

            with self.subTest(document=korean_document.relative_to(REPOSITORY_ROOT)):
                self.assertTrue(korean_lines[0].startswith("# "))
                self.assertEqual(korean_lines[1], "")
                self.assertEqual(korean_lines[2], korean_selector)

    def test_all_local_markdown_links_resolve_to_existing_files(self) -> None:
        for document in self.all_public_documents:
            for target in _local_link_targets(document):
                with self.subTest(
                    document=document.relative_to(REPOSITORY_ROOT),
                    target=target,
                ):
                    self.assertTrue(target.is_relative_to(REPOSITORY_ROOT))
                    self.assertTrue(target.exists())

    def test_cross_document_links_stay_in_the_source_language(self) -> None:
        english_set = set(self.english_documents)
        korean_set = self.expected_korean_documents

        for english_document in self.english_documents:
            allowed_selector_target = _korean_path(english_document)
            for target in _local_link_targets(english_document):
                if target not in korean_set or target == allowed_selector_target:
                    continue
                self.fail(
                    f"{english_document.relative_to(REPOSITORY_ROOT)} links to "
                    f"Korean document {target.relative_to(REPOSITORY_ROOT)}"
                )

        for korean_document in korean_set:
            english_document = korean_document.with_name(
                korean_document.name.removesuffix(".ko.md") + ".md"
            )
            for target in _local_link_targets(korean_document):
                if target not in english_set or target == english_document:
                    continue
                self.fail(
                    f"{korean_document.relative_to(REPOSITORY_ROOT)} links to "
                    f"English document {target.relative_to(REPOSITORY_ROOT)}"
                )


if __name__ == "__main__":
    unittest.main()
