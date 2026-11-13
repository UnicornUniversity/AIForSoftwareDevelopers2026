from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from src.tts.audio import sha256_file
from src.tts.importer import WavImportError, import_meeting_wav
from tests.conftest import write_wav


def _import(source: Path, destination: Path, manifest: Path, **kwargs):
    return import_meeting_wav(
        source,
        destination,
        fixture_id="controlled-sdlc-review-en",
        meeting_id="sdlc-review-2026-11-12",
        manifest_path=manifest,
        **kwargs,
    )


def test_import_copies_file_unchanged(tmp_path: Path) -> None:
    source = write_wav(tmp_path / "src" / "meeting.wav", seconds=0.4)
    destination = tmp_path / "audio" / "meeting.wav"
    manifest = _import(source, destination, tmp_path / "meeting_manifest.json")
    assert destination.read_bytes() == source.read_bytes()
    assert sha256_file(destination) == sha256_file(source)
    assert manifest.source == "imported"
    assert manifest.duration_seconds == pytest.approx(0.4, abs=0.01)


def test_imported_manifest_has_no_timeline(tmp_path: Path) -> None:
    source = write_wav(tmp_path / "meeting.wav", seconds=0.2)
    manifest = _import(
        source, tmp_path / "out" / "meeting.wav", tmp_path / "m.json"
    )
    assert manifest.timeline == ()
    assert manifest.turn_pause_ms == 0
    assert any("DER cannot be reported" in note for note in manifest.notes)
    saved = json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))
    assert saved["timeline"] == []
    assert saved["source"] == "imported"


def test_import_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(WavImportError, match="not found"):
        _import(
            tmp_path / "missing.wav",
            tmp_path / "out.wav",
            tmp_path / "m.json",
        )


def test_import_rejects_non_wav(tmp_path: Path) -> None:
    source = tmp_path / "meeting.wav"
    source.write_bytes(b"this is not audio")
    with pytest.raises(WavImportError):
        _import(source, tmp_path / "out.wav", tmp_path / "m.json")


def test_import_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    source = write_wav(tmp_path / "meeting.wav", seconds=0.1)
    destination = tmp_path / "out" / "meeting.wav"
    _import(source, destination, tmp_path / "m.json")
    with pytest.raises(WavImportError, match="already exists"):
        _import(source, destination, tmp_path / "m.json")


def test_import_force_replaces_destination(tmp_path: Path) -> None:
    source = write_wav(tmp_path / "meeting.wav", seconds=0.1)
    destination = tmp_path / "out" / "meeting.wav"
    _import(source, destination, tmp_path / "m.json")
    destination.write_bytes(b"stale")
    manifest = _import(source, destination, tmp_path / "m.json", force=True)
    assert destination.read_bytes() == source.read_bytes()
    assert manifest.duration_seconds == pytest.approx(0.1, abs=0.01)


def test_import_rejects_empty_wav(tmp_path: Path) -> None:
    source = tmp_path / "empty.wav"
    import soundfile as sf

    sf.write(source, np.zeros((0, 1), dtype=np.int16), 24_000, subtype="PCM_16")
    with pytest.raises(WavImportError, match="no audio frames"):
        _import(source, tmp_path / "out.wav", tmp_path / "m.json")


def test_import_rejects_same_source_and_destination(tmp_path: Path) -> None:
    source = write_wav(tmp_path / "meeting.wav", seconds=0.1)
    with pytest.raises(WavImportError, match="same file"):
        _import(source, source, tmp_path / "m.json")
