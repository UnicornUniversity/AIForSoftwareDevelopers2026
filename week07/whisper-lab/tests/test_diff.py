import tempfile
import unittest
from pathlib import Path
from unittest import mock

from whisper_lab import diff as diff_module
from whisper_lab.diff import align, compare, find_reference, render_page, split_words
from whisper_lab.engine import Segment, Transcription


def transcription() -> Transcription:
    return Transcription(
        text="Hello there. General Kenobi.",
        segments=[Segment(start=0.0, end=2.5, text=" Hello there.")],
        language="en",
        language_probability=0.98,
        duration=63.0,
        elapsed=6.0,
        model="small",
        device="cpu",
        compute_type="int8",
    )


class TokenTests(unittest.TestCase):
    def test_split_words_keeps_separators(self):
        parts = split_words("Hello  there\nworld!")
        self.assertEqual(
            parts,
            [("", "Hello"), ("  ", "there"), ("\n", "world"), ("!", "")],
        )


class ComparisonTests(unittest.TestCase):
    def test_identical_text_has_no_differences(self):
        result = compare("Hello there. General Kenobi.", "Hello there. General Kenobi.")
        self.assertEqual(result.stats.wer, 0.0)
        self.assertEqual(result.stats.matched, 4)
        self.assertNotIn('class="diff"', result.reference_html)
        self.assertNotIn('class="diff"', result.hypothesis_html)
        self.assertIn('<span class="same">Hello</span>', result.reference_html)

    def test_letters_are_compared_case_insensitively(self):
        result = compare("Hello", "hello")
        self.assertEqual(result.stats.substitutions, 0)
        self.assertNotIn('class="diff"', result.hypothesis_html)

    def test_substituted_word_colours_only_differing_letters(self):
        result = compare("Závist", "Závlst")
        self.assertEqual(result.stats.substitutions, 1)
        self.assertIn('<span class="same">Záv</span>', result.reference_html)
        self.assertIn('<span class="diff">i</span>', result.reference_html)
        # The tail matches again after the wrong letter.
        self.assertIn('<span class="same">st</span>', result.reference_html)
        self.assertIn('<span class="diff">l</span>', result.hypothesis_html)

    def test_inserted_word_is_red_in_the_transcript_only(self):
        result = compare("one two three", "one two extra three")
        self.assertEqual(result.stats.insertions, 1)
        self.assertEqual(result.stats.reference_words, 3)
        self.assertAlmostEqual(result.stats.wer, 1 / 3)
        self.assertIn('<span class="diff">extra</span>', result.hypothesis_html)
        self.assertNotIn('class="diff"', result.reference_html)

    def test_missing_word_is_red_in_the_reference_only(self):
        result = compare("one two three", "one three")
        self.assertEqual(result.stats.deletions, 1)
        self.assertAlmostEqual(result.stats.wer, 1 / 3)
        self.assertIn('<span class="diff">two</span>', result.reference_html)
        self.assertNotIn('class="diff"', result.hypothesis_html)

    def test_punctuation_is_not_compared(self):
        result = compare("Wait, stop!", "Wait stop")
        self.assertEqual(result.stats.wer, 0.0)
        self.assertNotIn('class="diff"', result.reference_html)
        # The comma and the exclamation mark are kept in the output, uncoloured.
        self.assertIn(",", result.reference_html)
        self.assertIn("!", result.reference_html)

    def test_empty_reference_does_not_divide_by_zero(self):
        result = compare("", "hello")
        self.assertIsNone(result.stats.wer)
        self.assertEqual(result.stats.insertions, 1)
        page = render_page(
            result,
            transcription(),
            audio_name="demo.wav",
            reference_name="demo.reference.txt",
            generated_at="2026-01-01 00:00",
        )
        self.assertIn("<dd>—</dd>", page)


class AlignmentTests(unittest.TestCase):
    def test_exact_alignment_pairs_surrounding_words(self):
        pairs = align(["one", "two", "three"], ["one", "three"])
        self.assertEqual(
            [(pair.reference, pair.hypothesis, pair.tag) for pair in pairs],
            [(0, 0, "equal"), (1, None, "delete"), (2, 1, "equal")],
        )

    def test_approximate_fallback_is_used_for_very_long_inputs(self):
        with mock.patch.object(diff_module, "MAX_ALIGNMENT_CELLS", 0):
            pairs = align(["one", "two", "three"], ["one", "three"])
        self.assertEqual(
            [(pair.reference, pair.hypothesis, pair.tag) for pair in pairs],
            [(0, 0, "equal"), (1, None, "delete"), (2, 1, "equal")],
        )


class EscapingTests(unittest.TestCase):
    def test_html_in_the_text_is_escaped(self):
        result = compare("a <b> c", "a x c")
        self.assertIn("&lt;", result.reference_html)
        self.assertIn("&gt;", result.reference_html)
        self.assertNotIn("<b>", result.reference_html)

    def test_page_escapes_the_names_but_keeps_the_markup(self):
        result = compare("<script>alert(1)</script>", "script alert 1 script")
        page = render_page(
            result,
            transcription(),
            audio_name="<evil>.wav",
            reference_name="<evil>.reference.txt",
            generated_at="2026-01-01 00:00",
        )
        self.assertNotIn("<script>", page)
        self.assertNotIn("<evil>", page)
        self.assertIn("&lt;evil&gt;.wav", page)


class PageTests(unittest.TestCase):
    def test_page_is_self_contained_and_reports_the_run(self):
        result = compare("Hello there. General Kenobi.", "Hello there. General Kenobi.")
        page = render_page(
            result,
            transcription(),
            audio_name="demo1.wav",
            reference_name="demo1.reference.txt",
            generated_at="2026-01-01 00:00",
        )
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn("<style>", page)
        self.assertIn("demo1.wav", page)
        self.assertIn("demo1.reference.txt", page)
        self.assertIn("small on cpu (int8)", page)
        self.assertIn("0.0%", page)
        self.assertIn("2026-01-01 00:00", page)
        self.assertNotIn("<link", page)  # no external assets
        self.assertNotIn("<script", page)
        self.assertTrue(page.rstrip().endswith("</html>"))


class ReferenceLookupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.samples = self.root / "samples"
        self.samples.mkdir()
        self.audio = self.root / "demo2.wav"
        self.audio.write_bytes(b"not really audio")

    def tearDown(self):
        self.directory.cleanup()

    def test_finds_the_stem_reference_in_samples(self):
        reference = self.samples / "demo2.reference.txt"
        reference.write_text("original", encoding="utf-8")
        self.assertEqual(find_reference(self.audio, self.samples), reference)

    def test_finds_a_reference_next_to_the_audio(self):
        reference = self.root / "demo2.reference.txt"
        reference.write_text("original", encoding="utf-8")
        self.assertEqual(find_reference(self.audio, self.samples), reference)

    def test_prefers_the_convention_over_the_numbered_name(self):
        preferred = self.samples / "demo2.reference.txt"
        preferred.write_text("new", encoding="utf-8")
        legacy = self.samples / "demo.reference2.txt"
        legacy.write_text("old", encoding="utf-8")
        self.assertEqual(find_reference(self.audio, self.samples), preferred)

    def test_accepts_the_numbered_name_of_the_bundled_clip(self):
        legacy = self.samples / "demo.reference1.txt"
        legacy.write_text("original", encoding="utf-8")
        self.assertEqual(find_reference(self.root / "demo1.wav", self.samples), legacy)

    def test_returns_none_when_there_is_no_reference(self):
        self.assertIsNone(find_reference(self.audio, self.samples))


if __name__ == "__main__":
    unittest.main()
