"""File-backed video source, exercised on a video generated during the test."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from drone_vision_lab.adapters.video import FileVideoSource, make_video_source
from drone_vision_lab.errors import HardwareUnavailableError, VisionError
from drone_vision_lab.interfaces import VideoSource, VideoSourceState, VideoSourceStatus
from drone_vision_lab.interfaces.video import VideoSourceState as State


def test_file_source_satisfies_the_protocol(sample_video):
    assert isinstance(FileVideoSource(str(sample_video)), VideoSource)


def test_open_reads_frames_with_increasing_index(sample_video):
    source = FileVideoSource(str(sample_video))
    source.open()
    first = source.read()
    second = source.read()
    assert first is not None and second is not None
    assert (first.index, second.index) == (0, 1)
    assert first.image.shape == (48, 64, 3)
    assert first.image.dtype == np.uint8
    assert second.captured_at >= first.captured_at
    source.close()


def test_end_of_file_stops_the_source(sample_video):
    source = FileVideoSource(str(sample_video))
    source.open()
    frames = 0
    while source.read() is not None:
        frames += 1
        assert frames < 100, "source never reached end of file"
    assert frames > 0
    assert source.state is State.ENDED
    assert source.status is VideoSourceStatus.ENDED
    source.close()


class _RaisingCapture:
    """A capture whose decoder fails instead of reporting the end of the file."""

    def isOpened(self) -> bool:
        return True

    def get(self, _prop: int) -> float:
        return 0.0

    def set(self, _prop: int, _value: float) -> bool:
        return True

    def read(self) -> tuple[bool, None]:
        raise RuntimeError("decoder failure at the last frame")

    def release(self) -> None:
        pass


def test_a_decode_error_is_an_end_of_file_not_a_broken_source(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"the fake decoder below does not read this")
    fake_cv2 = SimpleNamespace(
        CAP_PROP_FPS=5,
        CAP_PROP_FRAME_COUNT=6,
        CAP_PROP_FRAME_WIDTH=7,
        CAP_PROP_FRAME_HEIGHT=8,
        CAP_PROP_POS_FRAMES=9,
        VideoCapture=lambda _path: _RaisingCapture(),
    )
    source = FileVideoSource(str(video), cv2_module=fake_cv2)
    source.open()

    assert source.read() is None
    assert source.state is State.ENDED
    assert source.status is VideoSourceStatus.ENDED


def test_seek_from_the_end_makes_the_clip_playable_again(sample_video):
    source = FileVideoSource(str(sample_video))
    source.open()
    while source.read() is not None:
        pass
    assert source.state is State.ENDED

    assert source.seek(0.0) is True
    assert source.state is State.READY
    frame = source.read()
    assert frame is not None
    assert frame.index == 0
    source.close()


def test_looping_restarts_at_the_beginning(sample_video):
    source = FileVideoSource(str(sample_video))
    source.open()
    source.set_looping(True)
    seen = []
    for _ in range(source.frame_count + 3):
        frame = source.read()
        assert frame is not None
        seen.append(frame.index)
    assert seen[0] == 0
    assert seen[source.frame_count] == 0
    source.close()


def test_seek_moves_the_next_frame(sample_video):
    source = FileVideoSource(str(sample_video))
    source.open()
    assert source.seek(0.5) is True  # 10 fps -> frame 5
    frame = source.read()
    assert frame is not None
    assert frame.index == 5
    assert source.seek(-1.0) is False
    source.close()


def test_pause_and_resume(sample_video):
    source = FileVideoSource(str(sample_video))
    source.open()
    source.pause()
    assert source.state is State.PAUSED
    assert source.read() is None
    assert source.status is VideoSourceStatus.STALE
    source.resume()
    assert source.read() is not None
    source.close()


def test_missing_file_reports_clearly(tmp_path):
    source = FileVideoSource(str(tmp_path / "absent.mp4"))
    with pytest.raises(HardwareUnavailableError):
        source.open()
    assert source.state is State.ERROR


def test_unreadable_file_reports_clearly(tmp_path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"this is not a video")
    source = FileVideoSource(str(broken))
    with pytest.raises(VisionError):
        source.open()
    assert source.state is State.ERROR


def test_factory_builds_file_and_synthetic_sources(sample_video):
    synthetic = make_video_source("synthetic")
    assert isinstance(synthetic, VideoSource)
    file_source = make_video_source("file", str(sample_video))
    assert isinstance(file_source, FileVideoSource)
    with pytest.raises(ValueError):
        make_video_source("webcam")
    with pytest.raises(ValueError):
        make_video_source("file", None)


def test_closed_source_reads_nothing(sample_video):
    source = FileVideoSource(str(sample_video))
    assert source.read() is None
    assert source.state is VideoSourceState.CLOSED
