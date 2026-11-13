import json
import unittest

from whisper_lab.engine import Segment, Transcription
from whisper_lab.formats import (
    format_duration,
    format_timestamp,
    render,
    srt_timestamp,
    to_srt,
    to_vtt,
    vtt_timestamp,
)


def make_transcription() -> Transcription:
    return Transcription(
        text=" Hello there. General Kenobi.",
        segments=[
            Segment(start=0.0, end=2.5, text=" Hello there."),
            Segment(start=61.25, end=63.0, text=" General Kenobi."),
        ],
        language="en",
        language_probability=0.98,
        duration=63.0,
        elapsed=6.0,
        model="small",
        device="cpu",
        compute_type="int8",
    )


class TimestampTests(unittest.TestCase):
    def test_srt_uses_comma_and_wraps_hours(self):
        self.assertEqual(srt_timestamp(0.0), "00:00:00,000")
        self.assertEqual(srt_timestamp(3661.5), "01:01:01,500")

    def test_vtt_uses_dot(self):
        self.assertEqual(vtt_timestamp(61.25), "00:01:01.250")

    def test_display_timestamp_short_and_long(self):
        self.assertEqual(format_timestamp(9), "00:09")
        self.assertEqual(format_timestamp(65), "01:05")
        self.assertEqual(format_timestamp(3661), "1:01:01")

    def test_duration_formats(self):
        self.assertEqual(format_duration(9), "9 s")
        self.assertEqual(format_duration(65), "1 min 5 s")
        self.assertEqual(format_duration(3661), "1 h 1 min 1 s")


class SubtitleTests(unittest.TestCase):
    def test_srt_structure(self):
        output = to_srt(make_transcription())
        self.assertIn("1\n00:00:00,000 --> 00:00:02,500\nHello there.", output)
        self.assertIn("2\n00:01:01,250 --> 00:01:03,000\nGeneral Kenobi.", output)

    def test_vtt_header_and_cues(self):
        output = to_vtt(make_transcription())
        self.assertTrue(output.startswith("WEBVTT\n\n"))
        self.assertIn("00:00:00.000 --> 00:00:02.500", output)


class JsonTests(unittest.TestCase):
    def test_json_round_trip(self):
        data = json.loads(render(make_transcription(), "json"))
        self.assertEqual(data["language"], "en")
        self.assertEqual(len(data["segments"]), 2)
        self.assertAlmostEqual(data["rtf"], 6.0 / 63.0)

    def test_unknown_format_is_a_clear_error(self):
        with self.assertRaises(ValueError):
            render(make_transcription(), "docx")


if __name__ == "__main__":
    unittest.main()
