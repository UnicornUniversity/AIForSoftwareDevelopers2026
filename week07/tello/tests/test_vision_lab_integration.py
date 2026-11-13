"""Vision Lab integration: one frame, three detectors, honest partial results.

The detectors are scripted fakes and the frame is synthetic, so these tests run
with no camera, no model and no Ollama service.
"""

from __future__ import annotations

import threading
import time

import numpy as np

from drone_vision_lab.domain import BoundingBox, Detection, DetectionResult, DetectorKind, Frame
from drone_vision_lab.fakes import FakeDetector
from drone_vision_lab.interfaces import VideoSourceStatus
from drone_vision_lab.state import AppStateSnapshot, SafetyState
from drone_vision_lab.ui.detection_overlay import KIND_COLORS, render_frame
from drone_vision_lab.ui.tabs.vision_lab import VisionLabTab

BOX = BoundingBox(0.25, 0.25, 0.25, 0.25)
TARGET = (Detection(label="ball", box=BOX, confidence=None),)
YOLO_TARGET = (Detection(label="sports ball", box=BOX, confidence=0.87),)


def _frame() -> Frame:
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    return Frame(image=image, captured_at=time.monotonic(), source_id="synthetic", index=7)


def _install(services, kind, *, detections=TARGET, error=None, ready=True) -> FakeDetector:
    detector = FakeDetector(kind=kind, detections=detections, error=error)
    if ready:
        detector.load()
    services.detectors[kind] = detector
    return detector


def _wait(qapp, predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _tab(services) -> VisionLabTab:
    return VisionLabTab(services)


def test_comparison_runs_both_frame_detectors_on_the_same_frame(qapp, services):
    opencv = _install(services, DetectorKind.OPENCV, detections=TARGET)
    yolo = _install(services, DetectorKind.YOLO, detections=YOLO_TARGET)
    tab = _tab(services)
    tab.set_mode("comparison")

    frame = _frame()
    tab._on_frame(frame)  # noqa: SLF001 - drives the pipeline deterministically
    assert _wait(qapp, lambda: len(tab.results) == 2)

    assert opencv.frames_seen == 1
    assert yolo.frames_seen == 1
    assert tab.results[DetectorKind.OPENCV].frame_timestamp == frame.captured_at
    assert tab.results[DetectorKind.YOLO].frame_timestamp == frame.captured_at
    assert tab.result_rows[DetectorKind.YOLO].confidence.text() == "0.87"
    assert tab.result_rows[DetectorKind.OPENCV].confidence.text() == "N/A"


def test_single_mode_analyzes_only_that_detector(qapp, services):
    opencv = _install(services, DetectorKind.OPENCV)
    yolo = _install(services, DetectorKind.YOLO)
    tab = _tab(services)
    tab.set_mode(DetectorKind.OPENCV)

    tab._on_frame(_frame())  # noqa: SLF001
    assert _wait(qapp, lambda: DetectorKind.OPENCV in tab.results)

    assert opencv.frames_seen == 1
    assert yolo.frames_seen == 0
    assert set(tab._visible_results()) == {DetectorKind.OPENCV}  # noqa: SLF001


def test_a_failing_detector_is_shown_as_an_error_and_is_not_replaced(qapp, services):
    _install(services, DetectorKind.OPENCV, detections=TARGET)
    _install(services, DetectorKind.YOLO, error="weights unreadable")
    tab = _tab(services)
    tab.set_mode("comparison")

    tab._on_frame(_frame())  # noqa: SLF001
    assert _wait(qapp, lambda: len(tab.results) == 2)

    opencv_row = tab.result_rows[DetectorKind.OPENCV]
    yolo_row = tab.result_rows[DetectorKind.YOLO]
    assert opencv_row.status.text() == "1 detection(s)"
    assert yolo_row.status.text() == "Error"
    assert "weights unreadable" in yolo_row.detail.text()
    # The YOLO slot keeps YOLO's failure; OpenCV does not stand in for it.
    assert tab.results[DetectorKind.YOLO].failed is True
    assert tab.results[DetectorKind.OPENCV].failed is False


def test_vlm_result_shows_its_age_and_never_a_confidence(qapp, services):
    tab = _tab(services)
    tab.set_mode(DetectorKind.VLM)
    result = DetectionResult(
        detector_name="Ollama VLM (llava:7b)",
        kind=DetectorKind.VLM,
        detections=(Detection(label="ball", box=BOX, confidence=None),),
        frame_timestamp=time.monotonic() - 1.2,
        processed_at=time.monotonic() - 1.0,
        latency_ms=800.0,
    )

    tab._on_vlm_result(result)  # noqa: SLF001 - simulates the poller
    row = tab.result_rows[DetectorKind.VLM]

    assert "s old" in row.age.text()
    assert row.confidence.text() == "N/A"
    assert "800 ms" in row.latency.text()
    assert tab.results[DetectorKind.VLM] is result


def test_dry_run_unlocks_only_the_detectors_that_passed(qapp, services):
    _install(services, DetectorKind.OPENCV, detections=TARGET)
    _install(services, DetectorKind.YOLO, error="no model")
    tab = _tab(services)
    tab.set_mode("comparison")
    tab._on_frame(_frame())  # noqa: SLF001
    assert _wait(qapp, lambda: len(tab.results) == 2)

    tab._on_dry_run()  # noqa: SLF001
    assert _wait(
        qapp,
        lambda: services.state.snapshot().dry_run_passed_kinds,
    )

    snapshot = services.state.snapshot()
    assert snapshot.dry_run_passed_kinds == ("opencv",)
    assert snapshot.dry_run_partial is True
    assert snapshot.safety_state is SafetyState.DRY_RUN_PASSED
    assert tab.autonomous_ready(DetectorKind.OPENCV) is True
    assert tab.autonomous_ready(DetectorKind.YOLO) is False
    assert "partial" in tab.workflow_detail.text().lower()


def test_dry_run_without_a_target_does_not_pass(qapp, services):
    _install(services, DetectorKind.OPENCV, detections=())
    tab = _tab(services)
    tab.set_mode(DetectorKind.OPENCV)
    tab._on_frame(_frame())  # noqa: SLF001
    assert _wait(qapp, lambda: DetectorKind.OPENCV in tab.results)

    tab._on_dry_run()  # noqa: SLF001
    assert _wait(qapp, lambda: "no target" in tab.workflow_detail.text().lower())

    snapshot = services.state.snapshot()
    assert snapshot.dry_run_passed_kinds == ()
    assert snapshot.safety_state is not SafetyState.DRY_RUN_PASSED
    assert tab.autonomous_ready(DetectorKind.OPENCV) is False


def test_the_vlm_can_never_unlock_autonomy(qapp, services):
    tab = _tab(services)
    services.state.update(
        safety_state=SafetyState.DRY_RUN_PASSED,
        dry_run_passed_kinds=("opencv", "yolo"),
    )

    assert tab.autonomous_ready(DetectorKind.VLM) is False


def test_dry_run_refuses_the_vlm_only_mode(qapp, services, monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(
        "drone_vision_lab.ui.tabs.vision_lab.widgets.show_error",
        lambda _parent, _title, error: shown.append(str(error)),
    )
    tab = _tab(services)
    tab.set_mode(DetectorKind.VLM)

    tab._on_dry_run()  # noqa: SLF001

    assert shown
    assert "advisory" in shown[0]


def test_overlay_marks_each_algorithm_in_a_distinct_colour():
    assert len(set(KIND_COLORS.values())) == 3
    frame = _frame()
    results = {
        DetectorKind.OPENCV: DetectionResult(
            detector_name="OpenCV",
            kind=DetectorKind.OPENCV,
            detections=TARGET,
            frame_timestamp=frame.captured_at,
            processed_at=frame.captured_at,
            latency_ms=3.0,
        ),
        DetectorKind.YOLO: DetectionResult(
            detector_name="YOLO",
            kind=DetectorKind.YOLO,
            detections=YOLO_TARGET,
            frame_timestamp=frame.captured_at,
            processed_at=frame.captured_at,
            latency_ms=90.0,
        ),
    }

    image = render_frame(frame, results, now=frame.captured_at)

    assert image.width() == 320
    assert image.height() == 240


def test_the_vision_lab_refuses_a_camera_owned_by_the_tello_flight_tab(
    qapp, services, monkeypatch
):
    shown: list[str] = []
    monkeypatch.setattr(
        "drone_vision_lab.ui.tabs.vision_lab.widgets.show_error",
        lambda _parent, _title, error: shown.append(str(error)),
    )
    services.state.update(
        video_active=True,
        video_source_type="tello",
        video_owner="tello_flight",
    )
    tab = _tab(services)

    tab._start_source("synthetic", None)  # noqa: SLF001

    assert shown and "Another tab" in shown[0]
    assert tab.source is None
    assert services.state.snapshot().video_owner == "tello_flight"


def test_the_vision_lab_refuses_a_camera_owned_by_the_object_feedback_tab(
    qapp, services, monkeypatch
):
    shown: list[str] = []
    monkeypatch.setattr(
        "drone_vision_lab.ui.tabs.vision_lab.widgets.show_error",
        lambda _parent, _title, error: shown.append(str(error)),
    )
    services.state.update(
        video_active=True,
        video_source_type="file",
        video_owner="object_feedback",
    )
    tab = _tab(services)

    tab._start_source("synthetic", None)  # noqa: SLF001

    assert shown and "Another tab" in shown[0]
    assert tab.source is None
    assert services.state.snapshot().video_owner == "object_feedback"


def test_the_vision_lab_only_treats_its_own_or_legacy_video_as_active(qapp, services):
    tab = _tab(services)

    own = AppStateSnapshot(video_active=True, video_owner="vision_lab")
    legacy = AppStateSnapshot(video_active=True, video_owner=None)
    other = AppStateSnapshot(video_active=True, video_owner="tello_flight")

    assert tab._owns_video(own) is True  # noqa: SLF001
    assert tab._owns_video(legacy) is True  # noqa: SLF001 - pre-ownership state
    assert tab._owns_video(other) is False  # noqa: SLF001


def test_a_successful_streamon_opens_the_camera(qapp, services, monkeypatch):
    """The token guard must not block the ordinary path."""
    services.drone_mode = "tello"
    assert services.drone.connect().ok
    services.state.update(drone_connected=True)
    tab = _tab(services)
    opened: list[str] = []
    monkeypatch.setattr(tab, "_start_source", lambda kind, path: opened.append(kind))

    tab.start_tello_camera()

    assert _wait(qapp, lambda: opened == ["tello"])


def test_a_stop_during_streamon_does_not_open_the_camera(qapp, services, monkeypatch):
    """Stop wins over an in-flight ``streamon``: no source, and the stream is off.

    ``streamon`` waits for a UDP reply on a worker. If the operator stops while
    that is pending, the acknowledgement must not reopen the camera afterwards;
    if the aircraft acknowledged anyway, the stream is turned back off.
    """
    services.drone_mode = "tello"
    assert services.drone.connect().ok
    services.state.update(drone_connected=True)
    tab = _tab(services)
    opened: list[str] = []
    monkeypatch.setattr(tab, "_start_source", lambda kind, path: opened.append(kind))

    entered = threading.Event()
    release = threading.Event()
    streamon = services.drone.start_video_stream

    def slow_streamon():
        entered.set()
        release.wait(5.0)
        return streamon()

    monkeypatch.setattr(services.drone, "start_video_stream", slow_streamon)

    tab.start_tello_camera()
    assert _wait(qapp, entered.is_set)

    tab.stop_source()  # the operator stops while streamon is still in flight
    release.set()

    assert _wait(qapp, lambda: not tab._camera_runner.busy)  # noqa: SLF001
    assert opened == []
    assert tab.source is None
    assert _wait(qapp, lambda: "streamoff" in services.drone.commands)


def test_a_synthetic_source_starts_and_the_workflow_tracks_it(qapp, services):
    tab = _tab(services)

    tab._start_source("synthetic", None)  # noqa: SLF001
    try:
        assert tab.source is not None
        assert services.state.snapshot().video_active is True
        assert tab.dry_run_button.isEnabled()
    finally:
        tab.stop_source()

    assert tab.source is None
    assert services.state.snapshot().video_active is False
    assert services.state.snapshot().dry_run_passed_kinds == ()


def test_an_ended_video_offers_replay_and_keeps_the_controls_usable(
    qapp, services, sample_video
):
    tab = _tab(services)
    tab._start_source("file", str(sample_video))  # noqa: SLF001
    try:
        assert _wait(
            qapp,
            lambda: tab.source is not None
            and tab.source.status is VideoSourceStatus.ENDED,
        )
        # The pump sets the source status on its own thread and delivers the
        # change as a queued signal; wait for the widget update it triggers.
        assert _wait(qapp, lambda: tab._play_button.text() == "Replay")  # noqa: SLF001

        # Reaching the end of the clip is not a failure: the detector controls
        # stay usable and the transport offers to play the file again.
        assert tab.source is not None
        assert tab._play_button.isEnabled()  # noqa: SLF001
        assert tab._play_button.text() == "Replay"  # noqa: SLF001
        assert tab.dry_run_button.isEnabled()
        assert tab.yolo_button.isEnabled()
        assert tab.vlm_button.isEnabled()

        tab._toggle_pause()  # noqa: SLF001
        assert tab._play_button.text() == "Pause"  # noqa: SLF001
        assert _wait(
            qapp,
            lambda: tab.source is not None
            and tab.source.status is VideoSourceStatus.LIVE,
        )
    finally:
        tab.stop_source()


def test_a_frame_queued_before_a_stop_is_ignored(qapp, services):
    tab = _tab(services)
    stale_seq = tab._source_seq  # noqa: SLF001
    tab.stop_source()

    tab._on_frame(_frame(), seq=stale_seq)  # noqa: SLF001

    assert tab.last_frame is None


def test_stopping_a_source_keeps_a_connected_aircraft_grounded(qapp, services):
    tab = _tab(services)
    services.state.update(
        drone_connected=True,
        safety_state=SafetyState.CONNECTED_GROUNDED,
    )

    tab.stop_source()

    snapshot = services.state.snapshot()
    assert snapshot.drone_connected is True
    assert snapshot.safety_state is SafetyState.CONNECTED_GROUNDED


def test_resetting_autonomy_returns_to_connected_grounded_when_connected(qapp, services):
    tab = _tab(services)
    services.state.update(
        drone_connected=True,
        safety_state=SafetyState.DRY_RUN_PASSED,
        dry_run_passed_kinds=("opencv",),
    )

    tab.stop_source()

    snapshot = services.state.snapshot()
    assert snapshot.safety_state is SafetyState.CONNECTED_GROUNDED
    assert snapshot.dry_run_passed_kinds == ()


def test_resetting_autonomy_without_a_connection_stays_disconnected(qapp, services):
    tab = _tab(services)
    services.state.update(
        drone_connected=False,
        safety_state=SafetyState.CALIBRATED,
    )

    tab.stop_source()

    snapshot = services.state.snapshot()
    assert snapshot.drone_connected is False
    assert snapshot.safety_state is SafetyState.DISCONNECTED


def test_analysis_that_finishes_after_a_stop_is_dropped(qapp, services):
    _install(services, DetectorKind.OPENCV)
    tab = _tab(services)
    tab.set_mode(DetectorKind.OPENCV)

    tab._on_frame(_frame())  # noqa: SLF001
    tab.stop_source()

    assert tab.last_frame is None
    assert tab.results == {}
    assert _wait(qapp, lambda: not tab._analysis_runner.busy)  # noqa: SLF001
    # The worker's answer was produced for a source that no longer exists.
    assert tab.results == {}
    assert tab.last_frame is None


def test_a_dry_run_result_that_arrives_after_a_stop_is_not_applied(qapp, services):
    _install(services, DetectorKind.OPENCV, detections=TARGET)
    tab = _tab(services)
    tab.set_mode(DetectorKind.OPENCV)
    tab._on_frame(_frame())  # noqa: SLF001
    assert _wait(qapp, lambda: DetectorKind.OPENCV in tab.results)

    tab._on_dry_run()  # noqa: SLF001
    tab.stop_source()
    assert _wait(qapp, lambda: not tab._dry_runner.busy)  # noqa: SLF001

    snapshot = services.state.snapshot()
    assert snapshot.safety_state is not SafetyState.DRY_RUN_PASSED
    assert snapshot.dry_run_passed_kinds == ()


def test_choosing_a_source_from_the_dropdown_starts_it(qapp, services):
    """The dropdown must start on a placeholder; Qt pre-selects item zero, and
    choosing the already-selected synthetic source would emit no change."""
    tab = _tab(services)

    assert tab.source_combo.currentData() is None
    assert tab.dry_run_button.isEnabled() is False

    tab.source_combo.setCurrentIndex(tab.source_combo.findData("synthetic"))
    try:
        assert tab.source is not None
        assert tab.dry_run_button.isEnabled() is True
    finally:
        tab.stop_source()

    assert tab.source_combo.currentData() is None
    assert tab.source is None


def test_the_video_file_dialog_starts_in_the_application_video_folder(
    services, monkeypatch, tmp_path
):
    from PySide6.QtWidgets import QFileDialog

    from drone_vision_lab.ui.tabs import vision_lab

    folder = tmp_path / "video"
    monkeypatch.setattr(vision_lab, "videos_dir", lambda: folder)
    seen: list[str] = []

    def fake_dialog(parent, caption, directory, filters):
        seen.append(directory)
        return "", ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(fake_dialog))
    tab = _tab(services)

    assert tab._prompt_for_file() is False  # noqa: SLF001 - the dialog is stubbed
    assert seen == [str(folder)]
    assert folder.is_dir()
