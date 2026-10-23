from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from bookbuild.manifest import load_manifest
from bookbuild.markdown import load_chapter
from bookbuild.plan import load_frontmatter, load_plan
from bookbuild.render import render_book
from bookbuild.settings import load_settings

from tests.helpers import make_fixture


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.fixture = make_fixture(self.root)
        self.settings = load_settings(self.fixture["settings"])
        self.plan = load_plan(self.fixture["book"] / "book.json")
        self.manifest = load_manifest(self.fixture["manifest"])
        self.frontmatter = load_frontmatter(self.fixture["book"] / "frontmatter.json")
        self.chapter = load_chapter(self.fixture["chapters"] / "01-ecology.md")
        self.output = render_book(
            self.settings,
            self.plan,
            self.manifest,
            [self.chapter],
            self.frontmatter,
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def part(self, name: str) -> str:
        with zipfile.ZipFile(self.output) as archive:
            return archive.read(name).decode("utf-8")

    def test_document_and_styles(self) -> None:
        document = self.part("word/document.xml")
        styles = self.part("word/styles.xml")

        self.assertIn('w:w="11906"', document)
        self.assertIn('w:h="16838"', document)
        self.assertIn('w:left="1984"', document)
        self.assertIn("Times New Roman", styles)
        self.assertIn("Arial", styles)
        self.assertIn('w:jc w:val="both"', styles)
        self.assertIn('w:line="360"', styles)
        self.assertIn('w:start="1"', document)

    def test_front_matter_order(self) -> None:
        document = self.part("word/document.xml")
        title = document.index("Fixture Book")
        abstract = document.index("This thesis describes a fixture kangaroo.")
        anotace = document.index("Tato práce popisuje fiktivního klokana.")
        contents = document.index("Contents")
        chapter = document.index("Ecology")
        self.assertLess(title, abstract)
        self.assertLess(abstract, anotace)
        self.assertLess(anotace, contents)
        self.assertLess(contents, chapter)

    def test_fields_and_footer(self) -> None:
        document = self.part("word/document.xml")
        settings = self.part("word/settings.xml")
        self.assertIn("TOC", document)
        self.assertIn("updateFields", settings)
        self.assertIn("PAGE", self.part("word/footer1.xml"))
        names = zipfile.ZipFile(self.output).namelist()
        footers = [name for name in names if name.startswith("word/footer")]
        self.assertEqual(len(footers), 1)

    def test_quotes_provenance_and_references(self) -> None:
        document = self.part("word/document.xml")
        self.assertIn("The alpha line runs east", document)
        self.assertIn("doc01 · Voss (2018)", document)
        self.assertIn("Table 1: Source documents cited in this thesis.", document)
        self.assertIn("Voss, E. M. (2018). Field Notes on a Fixture Kangaroo.", document)
        self.assertLess(
            document.index("Table 1: Source documents"),
            document.index("<w:tbl>"),
        )

    def test_chapter_heading_is_numbered(self) -> None:
        document = self.part("word/document.xml")
        self.assertIn("1  Ecology", document)
        self.assertIn("1.1  The Alpha Line", document)


if __name__ == "__main__":
    unittest.main()
