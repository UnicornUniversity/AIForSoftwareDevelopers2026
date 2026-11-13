"""Frame delivery worker."""

from __future__ import annotations

import time

from drone_vision_lab.fakes import SyntheticVideoSource
from drone_vision_lab.workers import FramePump


def _collect(pump: FramePump) -> list:
    received: list = []
    pump.frame_ready.connect(received.append)
    return received


def test_pump_once_emits_a_frame(qapp):
    source = SyntheticVideoSource(width=32, height=24)
    source.open()
    pump = FramePump(source)
    received = _collect(pump)

    frame = pump.pump_once()

    assert frame is not None
    assert received == [frame]


def test_pump_status_changes_are_reported_once(qapp):
    source = SyntheticVideoSource(width=32, height=24)
    source.open()
    pump = FramePump(source)
    statuses: list = []
    pump.status_changed.connect(statuses.append)

    pump.pump_once()
    pump.pump_once()

    assert len(statuses) == 1


def test_pump_thread_delivers_several_frames_and_stops(qapp):
    source = SyntheticVideoSource(width=32, height=24)
    source.open()
    pump = FramePump(source, target_fps=60)
    received = _collect(pump)

    pump.start()
    deadline = time.monotonic() + 3.0
    while len(received) < 5 and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert pump.running
    pump.stop()
    assert not pump.running
    assert len(received) >= 5


def test_pump_stops_when_a_closed_source_returns_nothing(qapp):
    source = SyntheticVideoSource(width=32, height=24)
    pump = FramePump(source, target_fps=120)
    received = _collect(pump)
    pump.start()

    deadline = time.monotonic() + 2.0
    while pump.running and time.monotonic() < deadline:
        time.sleep(0.01)

    assert not received or len(received) < 3


def test_pump_reports_read_failures(qapp):
    class _Broken:
        status = None

        def read(self):
            raise RuntimeError("decoder exploded")

    pump = FramePump(_Broken())  # type: ignore[arg-type]
    failures: list[str] = []
    pump.failed.connect(failures.append)

    assert pump.pump_once() is None
    assert failures == ["decoder exploded"]
