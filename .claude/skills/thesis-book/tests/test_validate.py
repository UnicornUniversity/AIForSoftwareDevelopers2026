from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bookbuild.errors import ContentError
from bookbuild.extract import Extractor
from bookbuild.manifest import load_manifest
from bookbuild.markdown import load_chapter
from bookbuild.plan import load_frontmatter, load_plan
from bookbuild.settings import load_settings
from bookbuild.validate import quote_in_source, validate_book, validate_chapter
from bookbuild.typography import normalise_for_match

from tests.helpers import make_fixture


class ValidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.fixture = make_fixture(self.root)
        self.settings = load_settings(self.fixture["settings"])
        self.plan = load_plan(self.fixture["book"] / "book.json")
        self.manifest = load_manifest(self.fixture["manifest"])
        self.extractor = Extractor(self.root / "cache")
        entry = self.manifest.lookup("doc01")
        self.texts = {
            "doc01": self.extractor.load_or_extract(
                entry, entry.path(self.fixture["corpus"])
            )
        }

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_valid_chapter_passes(self) -> None:
        chapter = load_chapter(self.fixture["chapters"] / "01-ecology.md")
        warnings = validate_chapter(
            chapter,
            self.plan.chapters[0],
            self.manifest,
            self.texts,
            self.settings,
        )
        self.assertIsInstance(warnings, list)

    def test_missing_quote_is_reported(self) -> None:
        path = self.fixture["chapters"] / "01-ecology.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "The alpha line runs east—west and covers 1810–1960 m.",
                "The alpha line runs north-south and covers nothing.",
            ),
            encoding="utf-8",
        )
        chapter = load_chapter(path)
        with self.assertRaises(ContentError) as caught:
            validate_chapter(
                chapter,
                self.plan.chapters[0],
                self.manifest,
                self.texts,
                self.settings,
            )
        self.assertIn("not found verbatim", caught.exception.formatted)
        self.assertIn("doc01", caught.exception.formatted)

    def test_elided_quote_passes(self) -> None:
        source = "\n".join(self.texts["doc01"].paragraphs)
        quote = "The alpha line runs east—west … Twelve transects were walked at first light."
        self.assertTrue(quote_in_source(quote, normalise_for_match(source)))

    def test_unlisted_citation_fails(self) -> None:
        path = self.fixture["chapters"] / "01-ecology.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace("[doc01]", "[doc02]"),
            encoding="utf-8",
        )
        with self.assertRaises(ContentError) as caught:
            validate_chapter(
                load_chapter(path),
                self.plan.chapters[0],
                self.manifest,
                self.texts,
                self.settings,
            )
        self.assertIn("not listed", caught.exception.formatted)

    def test_missing_chapter_blocks_render(self) -> None:
        (self.fixture["chapters"] / "01-ecology.md").unlink()
        with self.assertRaises(ContentError) as caught:
            validate_book(
                self.settings,
                self.plan,
                self.manifest,
                self.extractor,
                require_upto=1,
            )
        self.assertIn("missing", caught.exception.formatted)

    def test_report_shape(self) -> None:
        report = validate_book(
            self.settings, self.plan, self.manifest, self.extractor
        )
        data = report.as_dict()
        self.assertEqual(data["chapters"][0]["number"], 1)
        self.assertTrue(data["chapters"][0]["authored"])
        self.assertEqual(data["used_sources"], ["doc01"])
        self.assertTrue(data["frontmatter_complete"])
        self.assertEqual(data["next_chapter"], None)


if __name__ == "__main__":
    unittest.main()
