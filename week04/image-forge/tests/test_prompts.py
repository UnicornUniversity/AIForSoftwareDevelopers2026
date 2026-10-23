"""Tests for subject parsing and prompt composition."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import ConfigError, load_settings  # noqa: E402
from prompts import (  # noqa: E402
    build_prompt,
    collect_subjects,
    normalize_stem,
    parse_line_list,
    parse_markdown_table,
)


class NamingTest(unittest.TestCase):
    def test_lower_underscore(self):
        self.assertEqual(normalize_stem("First Bandit"), "first_bandit")

    def test_upper(self):
        self.assertEqual(normalize_stem("first bandit", case="upper"), "FIRST_BANDIT")

    def test_keep_case(self):
        self.assertEqual(normalize_stem("First Bandit", case="keep"), "First_Bandit")

    def test_custom_separator(self):
        self.assertEqual(
            normalize_stem("castle throne", case="lower", separator="-"),
            "castle-throne",
        )

    def test_hyphens_follow_the_separator(self):
        self.assertEqual(normalize_stem("forest-path"), "forest_path")

    def test_punctuation_is_stripped(self):
        self.assertEqual(normalize_stem("Dr. Orc's (guard)"), "dr_orcs_guard")

    def test_empty_result_is_rejected(self):
        with self.assertRaises(ConfigError):
            normalize_stem("!!!")


class SourceParsingTest(unittest.TestCase):
    def test_markdown_table_reads_second_column_as_description(self):
        text = """
# Heading

| Name | Subject |
|---|---|
| `captain-vega` | a veteran captain |
| engineer | a young engineer |
"""
        self.assertEqual(
            parse_markdown_table(text),
            [("captain-vega", "a veteran captain"), ("engineer", "a young engineer")],
        )

    def test_markdown_header_is_skipped(self):
        text = "| ID | Note |\n|---|---|\n| first bat | big |\n"
        self.assertEqual(parse_markdown_table(text), [("first bat", "big")])

    def test_line_list_supports_comments_bullets_and_pipes(self):
        text = """
# A comment
ion-cell | a glowing cell
- plasma-coil
scrap-plate
"""
        self.assertEqual(
            parse_line_list(text),
            [
                ("ion-cell", "a glowing cell"),
                ("plasma-coil", ""),
                ("scrap-plate", ""),
            ],
        )


class CollectAndPromptTest(unittest.TestCase):
    def make_settings(self, body: str, files: dict[str, str] | None = None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for name, text in (files or {}).items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        path = root / "settings.yaml"
        path.write_text(body, encoding="utf-8")
        return load_settings(path)

    def test_inline_list_and_mapping(self):
        settings = self.make_settings(
            """
tasks:
  listed:
    prompt: "A picture of {subject}."
    subjects:
      - plain
  described:
    prompt: "A picture of {subject}."
    subjects:
      described: a red balloon
      detailed:
        subject: a blue kite
        extra: Windy sky.
"""
        )
        self.assertEqual([s.stem for s in collect_subjects(settings, "listed")], ["plain"])
        subjects = collect_subjects(settings, "described")
        self.assertEqual([s.stem for s in subjects], ["described", "detailed"])
        self.assertEqual(subjects[0].description, "a red balloon")
        self.assertEqual(subjects[1].description, "a blue kite")
        self.assertEqual(subjects[1].extra, "Windy sky.")

    def test_source_file_is_read_before_inline_subjects(self):
        settings = self.make_settings(
            """
tasks:
  demo:
    source: list.txt
    prompt: "A picture of {subject}."
    subjects:
      inline: an inline subject
""",
            {"list.txt": "from-file | a file subject\n"},
        )
        subjects = collect_subjects(settings, "demo")
        self.assertEqual([s.stem for s in subjects], ["from_file", "inline"])

    def test_base_resolves_to_subject_stem(self):
        settings = self.make_settings(
            """
tasks:
  demo:
    prompt: "A picture of {subject}."
    subjects:
      base-one: the base
      variant:
        subject: the variant
        base: base-one
"""
        )
        subjects = collect_subjects(settings, "demo")
        self.assertEqual(subjects[1].base, "base_one")

    def test_duplicate_stem_is_rejected(self):
        settings = self.make_settings(
            """
tasks:
  demo:
    source: list.txt
    prompt: "A picture of {subject}."
    subjects:
      from-file: a duplicate
""",
            {"list.txt": "from-file | first\n"},
        )
        with self.assertRaisesRegex(ConfigError, "both map to"):
            collect_subjects(settings, "demo")

    def test_self_base_is_rejected(self):
        settings = self.make_settings(
            """
tasks:
  demo:
    prompt: "A picture of {subject}."
    subjects:
      one:
        subject: one
        base: one
"""
        )
        with self.assertRaisesRegex(ConfigError, "cannot use itself"):
            collect_subjects(settings, "demo")

    def test_prompt_composition_order_and_placeholders(self):
        settings = self.make_settings(
            """
style: STYLE
tasks:
  demo:
    style_extra: EXTRA
    prompt: "A picture of {subject} named {stem} in {task}."
    subjects:
      my-item:
        subject: a red balloon
        extra: SUBJECT EXTRA
"""
        )
        subject = collect_subjects(settings, "demo")[0]
        prompt = build_prompt(settings, "demo", subject)
        self.assertEqual(
            prompt,
            "\n\n".join(
                [
                    "STYLE",
                    "EXTRA",
                    "A picture of a red balloon named my_item in demo.",
                    "SUBJECT EXTRA",
                ]
            ),
        )

    def test_task_style_replaces_global_style(self):
        settings = self.make_settings(
            """
style: GLOBAL
tasks:
  demo:
    style: LOCAL
    prompt: "A picture of {subject}."
    subjects: [one]
"""
        )
        subject = collect_subjects(settings, "demo")[0]
        self.assertEqual(build_prompt(settings, "demo", subject), "LOCAL\n\nA picture of one.")

    def test_subject_prompt_replaces_everything(self):
        settings = self.make_settings(
            """
style: GLOBAL
tasks:
  demo:
    prompt: "A picture of {subject}."
    subjects:
      one:
        prompt: VERBATIM
"""
        )
        subject = collect_subjects(settings, "demo")[0]
        self.assertEqual(build_prompt(settings, "demo", subject), "VERBATIM")

    def test_empty_prompt_is_rejected(self):
        settings = self.make_settings(
            """
tasks:
  demo:
    subjects: [one]
"""
        )
        subject = collect_subjects(settings, "demo")[0]
        with self.assertRaisesRegex(ConfigError, "no prompt text"):
            build_prompt(settings, "demo", subject)


if __name__ == "__main__":
    unittest.main()
