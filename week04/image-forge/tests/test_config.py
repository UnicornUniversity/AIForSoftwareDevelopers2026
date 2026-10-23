"""Tests for settings loading, merging, and validation."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    ConfigError,
    DEFAULT_APPEARANCE,
    deep_merge,
    load_settings,
    resolve_appearance,
)

MINIMAL_TASK = """
tasks:
  demo:
    prompt: "A picture of {subject}."
    subjects: [one]
"""


class SettingsTest(unittest.TestCase):
    def load(self, body: str, *, name: str = "settings.yaml"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / name
        path.write_text(body, encoding="utf-8")
        return load_settings(path)

    def test_deep_merge_preserves_siblings(self):
        merged = deep_merge(
            {"a": {"x": 1, "y": 2}, "b": 3},
            {"a": {"y": 9}},
        )
        self.assertEqual(merged, {"a": {"x": 1, "y": 9}, "b": 3})

    def test_relative_paths_resolve_from_settings_file(self):
        settings = self.load(MINIMAL_TASK)
        self.assertEqual(settings.base_dir, settings.path.parent)

    def test_unknown_top_level_key_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "unknown setting"):
            self.load(MINIMAL_TASK + "\napparence: {}\n")

    def test_unknown_appearance_key_is_rejected(self):
        body = "appearance:\n  qality: high\n" + MINIMAL_TASK
        with self.assertRaisesRegex(ConfigError, "unknown setting"):
            self.load(body)

    def test_appearance_preset_merges_over_global(self):
        body = """
appearance:
  quality: medium
  size: 1024x1024
appearance_presets:
  wide:
    size: 1536x1024
    key_out: {enabled: true}
tasks:
  demo:
    appearance: wide
    prompt: "x {subject}"
    subjects: [one]
"""
        settings = self.load(body)
        task = settings.tasks["demo"]
        appearance = resolve_appearance(settings, task)
        self.assertEqual(appearance["size"], "1536x1024")
        self.assertEqual(appearance["quality"], "medium")
        self.assertTrue(appearance["key_out"]["enabled"])
        # Unspecified nested keys keep their defaults.
        self.assertEqual(appearance["key_out"]["mode"], "global")

    def test_appearance_list_applies_in_order(self):
        body = """
appearance_presets:
  base: {size: 1536x1024, quality: medium}
  draft: {quality: low}
tasks:
  demo:
    appearance: [base, draft]
    prompt: "x {subject}"
    subjects: [one]
"""
        settings = self.load(body)
        appearance = resolve_appearance(settings, settings.tasks["demo"])
        self.assertEqual(appearance["size"], "1536x1024")
        self.assertEqual(appearance["quality"], "low")

    def test_unknown_preset_is_rejected(self):
        body = """
tasks:
  demo:
    appearance: nope
    prompt: "x {subject}"
    subjects: [one]
"""
        settings = self.load(body)
        with self.assertRaisesRegex(ConfigError, "unknown appearance preset"):
            resolve_appearance(settings, settings.tasks["demo"])

    def test_jpeg_with_transparency_is_rejected(self):
        body = """
appearance:
  format: jpeg
  key_out: {enabled: true}
tasks:
  demo:
    prompt: "x {subject}"
    subjects: [one]
"""
        with self.assertRaisesRegex(ConfigError, "jpeg cannot store"):
            self.load(body)

    def test_normalize_without_alpha_is_rejected(self):
        body = """
appearance:
  normalize: {enabled: true}
tasks:
  demo:
    prompt: "x {subject}"
    subjects: [one]
"""
        with self.assertRaisesRegex(ConfigError, "needs transparency"):
            self.load(body)

    def test_gpt_image_size_is_checked(self):
        body = "appearance:\n  size: 800x600\n" + MINIMAL_TASK
        with self.assertRaisesRegex(ConfigError, "not supported"):
            self.load(body)

    def test_non_gpt_image_model_accepts_other_sizes(self):
        body = "appearance:\n  model: some-image-model\n  size: 800x600\n" + MINIMAL_TASK
        settings = self.load(body)
        self.assertEqual(settings.appearance["size"], "800x600")

    def test_defaults_are_complete(self):
        settings = self.load(MINIMAL_TASK)
        self.assertEqual(settings.appearance, DEFAULT_APPEARANCE)


if __name__ == "__main__":
    unittest.main()
