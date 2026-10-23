from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bookbuild.errors import CorpusError
from bookbuild.manifest import load_manifest, match_key, repair_mojibake

from tests.helpers import PROJECT


class ManifestTests(unittest.TestCase):
    def test_real_corpus_manifest(self) -> None:
        path = PROJECT / "coprus" / "manifest.json"
        if not path.is_file():
            self.skipTest("the corpus is not present")
        manifest = load_manifest(path)
        self.assertEqual(len(manifest.documents), 30)
        entry = manifest.lookup("doc02")
        self.assertEqual(entry.year, 2023)
        self.assertIn("Marchetti", entry.authors[0])
        self.assertEqual(entry.citation, "(Marchetti et al., 2023)")
        self.assertTrue(entry.has_contradiction is False)

    def test_mojibake_repair(self) -> None:
        damaged = "Policy Timeline (1998â€“2024)"
        self.assertEqual(repair_mojibake(damaged), "Policy Timeline (1998–2024)")
        clean = "An em dash — stays"
        self.assertEqual(repair_mojibake(clean), clean)

    def test_match_key_ignores_punctuation_and_damage(self) -> None:
        self.assertEqual(
            match_key("(1998â€“2024)"),
            match_key("(1998–2024)"),
        )

    def test_duplicate_ids_rejected(self) -> None:
        document = {
            "id": "doc01",
            "filename": "doc01-a.docx",
            "format": "docx",
            "sub_topic": "ecology",
            "title": "A",
            "word_count": 1,
            "target_words": 1,
            "has_contradiction": False,
        }
        raw = {"count": 2, "documents": [document, dict(document, filename="doc01-b.docx")]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(CorpusError):
                load_manifest(path)

    def test_count_must_match(self) -> None:
        raw = {"count": 5, "documents": []}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(CorpusError):
                load_manifest(path)


if __name__ == "__main__":
    unittest.main()
