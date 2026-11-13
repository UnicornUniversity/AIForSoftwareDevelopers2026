"""Synthetic ASR outputs and timelines for the evaluation tests.

Everything here is offline and small: the tests never read a real ASR run, never
touch a model, and never call a network service.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, Sequence

from src.fixtures import Fixture
from src.schema import NormalizedTranscript, TranscriptSegment, write_json

DEFAULT_LABELS = {
    "whisperx": {"ANN": "SPEAKER_00", "BOB": "SPEAKER_01", "GREG": "SPEAKER_02"},
    "gemini": {"ANN": "spk_1", "BOB": "spk_2", "GREG": "spk_3"},
}


def turn_spans(
    fixture: Fixture, *, per_turn: float = 1.0, pause: float = 0.35
) -> list[tuple[int, float, float]]:
    spans: list[tuple[int, float, float]] = []
    time = 0.0
    for turn in fixture.ground_truth.turns:
        spans.append((turn.index, time, time + per_turn))
        time += per_turn + pause
    return spans


def make_transcript(
    fixture: Fixture,
    spans: Sequence[tuple[int, float, float]],
    labels: Mapping[str, str],
    *,
    system: str = "whisperx",
    model: str = "small.en",
    mutate_turn: int | None = None,
    mutate: Callable[[str], str] | None = None,
) -> NormalizedTranscript:
    segments: list[TranscriptSegment] = []
    for (index, start, end), turn in zip(spans, fixture.ground_truth.turns):
        text = turn.text
        if mutate_turn is not None and turn.index == mutate_turn and mutate:
            text = mutate(text)
        segments.append(
            TranscriptSegment(
                index=index,
                start=start,
                end=end,
                text=text,
                speaker_label=labels[turn.speaker_id],
            )
        )
    return NormalizedTranscript(
        schema_version="1.0",
        fixture_id=fixture.script.fixture_id,
        meeting_id=fixture.script.meeting_id,
        system=system,
        model=model,
        language="en",
        segments=tuple(segments),
    )


def write_meeting_manifest(
    path: Path,
    fixture: Fixture,
    spans: Sequence[tuple[int, float, float]],
) -> Path:
    audio_file = str(Path(path).parent / "meeting.wav")
    duration = max(end for _, _, end in spans)
    payload = {
        "schema_version": "1.0",
        "fixture_id": fixture.script.fixture_id,
        "meeting_id": fixture.script.meeting_id,
        "audio_file": audio_file,
        "source": "tts",
        "model": "gemini-3.8-flash-tts",
        "sample_rate": 24_000,
        "channels": 1,
        "sample_width_bytes": 2,
        "duration_seconds": duration,
        "turn_pause_ms": 350,
        "section_pause_ms": 900,
        "timeline": [
            {
                "index": index,
                "speaker_id": fixture.ground_truth.turns[index - 1].speaker_id,
                "text": fixture.ground_truth.turns[index - 1].text,
                "start_seconds": start,
                "end_seconds": end,
                "pause_after_seconds": 0.35,
            }
            for index, start, end in spans
        ],
        "environment": {},
        "notes": ["synthetic timeline for tests"],
    }
    write_json(Path(path), payload)
    return Path(path).parent / "meeting.wav"


def write_system(
    out_dir: Path,
    transcript: NormalizedTranscript,
    *,
    audio_file: str,
    timing: Mapping[str, float] | None = None,
    asr: Mapping[str, object] | None = None,
    extra: Mapping[str, object] | None = None,
) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "transcript.json", transcript.to_dict())
    duration = max(
        (segment.end for segment in transcript.segments), default=0.0
    )
    manifest = {
        "schema_version": "1.0",
        "system": transcript.system,
        "audio": {"file": audio_file, "duration_seconds": duration},
        "asr": dict(asr or {"model": transcript.model}),
        "timing_seconds": dict(
            timing or {"total_pipeline": 1.5, "export": 0.1}
        ),
        "counts": {},
        "notes": [],
    }
    if extra:
        manifest.update(extra)
    write_json(out_dir / "run_manifest.json", manifest)
    return out_dir
