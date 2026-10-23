from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from bookbuild.errors import SettingsError
from bookbuild.settings import load_settings

from tests.helpers import PROJECT, settings_dict


def write(tmp: Path, data: dict) -> Path:
    path = tmp / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class SettingsTests(unittest.TestCase):
    def test_project_settings_are_valid(self) -> None:
        path = PROJECT / "settings.json"
        if not path.is_file():
            self.skipTest("the project settings are not present")
        settings = load_settings(path)
        self.assertEqual(settings.raw["page"]["size"], "A4")
        self.assertEqual(settings.raw["typography"]["body"]["font"], "Times New Roman")
        self.assertEqual(settings.raw["page"]["margins_cm"]["left"], 3.5)

    def test_unknown_key_names_the_path(self) -> None:
        data = settings_dict()
        data["page"]["margins_cm"]["gutter"] = 1
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SettingsError) as caught:
                load_settings(write(Path(directory), data))
        self.assertIn("page.margins_cm", caught.exception.formatted)
        self.assertIn("gutter", caught.exception.formatted)

    def test_margin_out_of_range(self) -> None:
        data = settings_dict()
        data["page"]["margins_cm"]["left"] = 12
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SettingsError) as caught:
                load_settings(write(Path(directory), data))
        self.assertIn("page.margins_cm.left", caught.exception.formatted)
        self.assertIn("at most 10", caught.exception.formatted)

    def test_bad_page_size(self) -> None:
        data = settings_dict()
        data["page"]["size"] = "A5"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SettingsError):
                load_settings(write(Path(directory), data))

    def test_missing_book_title(self) -> None:
        data = settings_dict()
        del data["book"]["title"]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SettingsError) as caught:
                load_settings(write(Path(directory), data))
        self.assertIn("book", caught.exception.formatted)

    def test_toc_depth_must_be_an_integer(self) -> None:
        data = copy.deepcopy(settings_dict())
        data["front_matter"]["table_of_contents"]["depth"] = 1.5
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SettingsError):
                load_settings(write(Path(directory), data))

    def test_bad_colour(self) -> None:
        data = settings_dict()
        data["typography"]["headings"]["color"] = "black"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SettingsError):
                load_settings(write(Path(directory), data))


if __name__ == "__main__":
    unittest.main()
