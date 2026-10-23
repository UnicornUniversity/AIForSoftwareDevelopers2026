from __future__ import annotations

import unittest

from bookbuild.typography import (
    apply,
    normalise_for_match,
    residual_issues,
    split_elision,
)

from tests.helpers import typography


class TypographyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = {"typography": typography()}

    def test_straight_quotes_become_english_smart_quotes(self) -> None:
        self.assertEqual(apply('He said "hello" today.', self.config["typography"]), "He said “hello” today.")

    def test_apostrophes_are_curly(self) -> None:
        self.assertEqual(apply("the kangaroo's pouch", self.config["typography"]), "the kangaroo’s pouch")

    def test_czech_opening_quote_becomes_english(self) -> None:
        result = apply("„text“", self.config["typography"])
        self.assertEqual(result, "“text”")
        self.assertNotIn("„", result)

    def test_double_hyphen_is_an_em_dash(self) -> None:
        self.assertEqual(apply("one--two", self.config["typography"]), "one—two")

    def test_spaced_hyphen_becomes_an_unspaced_em_dash(self) -> None:
        self.assertEqual(apply("one - two", self.config["typography"]), "one—two")

    def test_ranges_use_an_en_dash(self) -> None:
        self.assertEqual(apply("1998-2024", self.config["typography"]), "1998–2024")

    def test_iso_dates_are_not_ranges(self) -> None:
        self.assertEqual(apply("2026-10-23", self.config["typography"]), "2026-10-23")

    def test_compound_hyphens_are_untouched(self) -> None:
        self.assertEqual(apply("state-of-the-art", self.config["typography"]), "state-of-the-art")

    def test_no_non_breaking_space_is_inserted(self) -> None:
        result = apply("a kangaroo and I", self.config["typography"])
        self.assertNotIn(" ", result)

    def test_residual_issues_reports_straight_quotes(self) -> None:
        self.assertTrue(residual_issues('a "quote"'))
        self.assertTrue(residual_issues("an 'apostrophe'"))

    def test_normalise_for_match_folds_glyphs(self) -> None:
        self.assertEqual(
            normalise_for_match("The “alpha” line — 1998–2024..."),
            normalise_for_match('The "alpha" line - 1998-2024...'),
        )

    def test_split_elision(self) -> None:
        parts = split_elision("First part … second part [...] third")
        self.assertEqual(len(parts), 3)


if __name__ == "__main__":
    unittest.main()
