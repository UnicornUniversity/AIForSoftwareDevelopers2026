"""Guidance overlay geometry, colours and wording (no pixel inspection)."""

from __future__ import annotations

import time

import numpy as np

from drone_vision_lab.domain import BoundingBox, Detection, DetectionResult, DetectorKind, Frame
from drone_vision_lab.pursuit import PursuitAction, PursuitDecision
from drone_vision_lab.ui.guidance_overlay import (
    TARGET_COLOR,
    action_color,
    deadband_bounds,
    guidance_layout,
    render_guidance,
    render_target_overlay,
    select_target_box,
)


def _frame(width: int = 64, height: int = 48) -> Frame:
    return Frame(
        image=np.zeros((height, width, 3), dtype=np.uint8),
        captured_at=time.monotonic(),
        source_id="test",
        index=0,
    )


def _result(box: BoundingBox | None, *, error: str | None = None) -> DetectionResult:
    detections = (
        (Detection("apple", box, confidence=0.87),) if box is not None else ()
    )
    return DetectionResult(
        detector_name="YOLO",
        kind=DetectorKind.YOLO,
        detections=detections,
        frame_timestamp=0.0,
        processed_at=0.0,
        error=error,
    )


def _decision(
    action: PursuitAction,
    message: str = "Apple is left of center → yaw left 8°.",
    *,
    error: float | None = -0.25,
) -> PursuitDecision:
    return PursuitDecision(action=action, message=message, error=error)


def test_deadband_bounds_are_ten_percent_either_side():
    assert deadband_bounds(320) == (128.0, 192.0)
    assert deadband_bounds(0) == (0.0, 0.0)


def test_the_largest_box_is_the_target():
    small = BoundingBox(0.80, 0.80, 0.05, 0.05)
    large = BoundingBox(0.05, 0.30, 0.20, 0.30)
    result = DetectionResult(
        detector_name="YOLO",
        kind=DetectorKind.YOLO,
        detections=(
            Detection("apple", small, confidence=0.9),
            Detection("apple", large, confidence=0.5),
        ),
    )

    assert select_target_box(result) == large
    assert select_target_box(_result(None)) is None
    assert select_target_box(_result(None, error="boom")) is None


def test_the_target_is_green_and_the_banner_is_advisory():
    box = BoundingBox(0.20, 0.40, 0.10, 0.20)
    decision = _decision(PursuitAction.YAW_LEFT)

    layout = guidance_layout((320, 240), _result(box), decision)

    assert layout.target_color == TARGET_COLOR == "#34c759"
    assert layout.target_box == box
    assert layout.center_x == 160.0
    assert layout.deadband_left == 128.0
    assert layout.deadband_right == 192.0
    assert layout.error_px == -80.0
    assert layout.action is PursuitAction.YAW_LEFT
    assert layout.banner.startswith("ADVISORY ONLY — no command is sent.")


def test_action_colours_are_distinct_and_stable():
    assert action_color(PursuitAction.CENTERED) == TARGET_COLOR
    assert action_color(PursuitAction.YAW_LEFT) == "#f5a524"
    assert action_color(PursuitAction.YAW_RIGHT) == "#f5a524"
    assert action_color(PursuitAction.STOPPED) == "#b42318"
    assert action_color(PursuitAction.IDLE) != action_color(PursuitAction.CENTERED)


def test_layout_falls_back_to_the_target_box_when_no_error_is_set():
    box = BoundingBox(0.45, 0.40, 0.10, 0.20)  # centre x = 0.50
    decision = PursuitDecision(action=PursuitAction.CENTERED, message="Centered.")

    layout = guidance_layout((320, 240), _result(box), decision)

    assert layout.error_px == 0.0


def test_render_draws_a_normal_detection(qapp):
    image, layout = render_guidance(
        _frame(),
        _result(BoundingBox(0.20, 0.40, 0.10, 0.20)),
        _decision(PursuitAction.YAW_LEFT),
    )

    assert image.size().width() == 64
    assert image.size().height() == 48
    assert layout.target_box is not None
    assert not image.isNull()


def test_render_target_overlay_draws_only_the_green_boxes(qapp):
    box = BoundingBox(0.20, 0.40, 0.10, 0.20)

    image = render_target_overlay(_frame(), _result(box))

    assert image.size().width() == 64
    assert image.size().height() == 48
    assert image.isNull() is False
    # The overlay has no banner or deadband, so it starts as a copy of the
    # frame and only the box is painted. The chosen box is the largest one.
    assert select_target_box(_result(box)) == box
    assert render_target_overlay(_frame(), _result(None)).isNull() is False


def test_render_target_overlay_survives_a_failed_detector(qapp):
    image = render_target_overlay(
        _frame(), _result(BoundingBox(0.20, 0.40, 0.10, 0.20), error="boom")
    )

    assert image.size().width() == 64
    assert image.size().height() == 48
    assert image.isNull() is False


def test_render_survives_no_target_failed_and_stopped_inputs(qapp):
    cases = [
        (
            _result(None),
            _decision(PursuitAction.NO_TARGET, "No apple detected.", error=None),
        ),
        (
            _result(None, error="weights unreadable"),
            _decision(PursuitAction.STOPPED, "The detector failed.", error=None),
        ),
        (
            _result(BoundingBox(0.20, 0.40, 0.10, 0.20)),
            _decision(PursuitAction.STOPPED, "Detector results are stale.", error=None),
        ),
    ]

    for result, decision in cases:
        image, layout = render_guidance(_frame(), result, decision)
        assert image.size().width() == 64
        assert image.size().height() == 48
        assert layout.action is decision.action
        assert layout.banner.startswith("ADVISORY ONLY —")
