from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bookbuild.errors import ContentError
from bookbuild.markdown import load_chapter, parse_inline

CHAPTER = """---
chapter: 2
title: Movement and Migration
sources: doc06, doc24
---

Opening prose citing a source [doc06].

## Dusk Routes

> The migration begins within twenty minutes of sunset.
> — doc06

- first item
- second item with [doc24]
"""


class MarkdownTests(unittest.TestCase):
    def write(self, directory: str, text: str) -> Path:
        path = Path(directory) / "02-movement.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_parses_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chapter = load_chapter(self.write(directory, CHAPTER))
        self.assertEqual(chapter.number, 2)
        self.assertEqual(chapter.title, "Movement and Migration")
        self.assertEqual(chapter.sources, ["doc06", "doc24"])
        self.assertEqual(
            [block.kind for block in chapter.blocks],
            ["paragraph", "heading", "quote", "list_item", "list_item"],
        )
        quote = chapter.quotes[0]
        self.assertEqual(quote.source, "doc06")
        self.assertEqual(quote.text, "The migration begins within twenty minutes of sunset.")

    def test_inline_spans(self) -> None:
        spans = parse_inline("A **bold** and *italic* claim [doc06].", 1, None)
        bold = [span for span in spans if span.bold]
        italic = [span for span in spans if span.italic]
        citation = [span for span in spans if span.citation]
        self.assertEqual(bold[0].text, "bold")
        self.assertEqual(italic[0].text, "italic")
        self.assertEqual(citation[0].text, "[doc06]")

    def test_quote_without_marker_fails(self) -> None:
        text = CHAPTER.replace("> — doc06\n", "")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ContentError) as caught:
                load_chapter(self.write(directory, text))
        self.assertIn("provenance marker", caught.exception.formatted)

    def test_marker_inside_quote_fails(self) -> None:
        text = CHAPTER.replace(
            "> The migration begins within twenty minutes of sunset.\n> — doc06\n",
            "> The migration begins within twenty minutes of sunset.\n> — doc06\n> more text\n",
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ContentError):
                load_chapter(self.write(directory, text))

    def test_level_one_heading_fails(self) -> None:
        text = CHAPTER.replace("## Dusk Routes", "# Dusk Routes")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ContentError) as caught:
                load_chapter(self.write(directory, text))
        self.assertIn("level-1", caught.exception.formatted)

    def test_table_fails(self) -> None:
        text = CHAPTER.replace("Opening prose citing a source [doc06].", "| a | b |\n|---|---|")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ContentError) as caught:
                load_chapter(self.write(directory, text))
        self.assertIn("tables", caught.exception.formatted)

    def test_unknown_front_key_fails(self) -> None:
        text = CHAPTER.replace("title: Movement and Migration", "title: Movement\nstyle: fancy")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ContentError) as caught:
                load_chapter(self.write(directory, text))
        self.assertIn("unknown front-matter key", caught.exception.formatted)


if __name__ == "__main__":
    unittest.main()
