"""Domain value objects: validation and coordinate conversions."""

from __future__ import annotations

import numpy as np
import pytest

from drone_vision_lab.domain import (
    BoundingBox,
    CommandResult,
    CommandStatus,
    Detection,
    DetectionResult,
    DetectorKind,
    Frame,
    Telemetry,
)


def _frame(**kwargs) -> Frame:
    defaults = dict(
        image=np.zeros((480, 640, 3), dtype=np.uint8),
        captured_at=1.0,
        source_id="test",
        index=0,
    )
    defaults.update(kwargs)
    return Frame(**defaults)


# -- Frame -------------------------------------------------------------------


def test_frame_reports_dimensions():
    frame = _frame()
    assert frame.width == 640
    assert frame.height == 480
    assert frame.shape == (640, 480)


def test_frame_rejects_wrong_shape():
    with pytest.raises(ValueError, match="HxWx3"):
        _frame(image=np.zeros((480, 640), dtype=np.uint8))


def test_frame_rejects_wrong_dtype():
    with pytest.raises(ValueError, match="uint8"):
        _frame(image=np.zeros((10, 10, 3), dtype=np.float32))


def test_frame_rejects_empty_source_id():
    with pytest.raises(ValueError, match="source_id"):
        _frame(source_id="")


# -- BoundingBox -------------------------------------------------------------


def test_bounding_box_center_and_area():
    box = BoundingBox(0.1, 0.2, 0.4, 0.2)
    assert box.center == pytest.approx((0.3, 0.3))
    assert box.area == pytest.approx(0.08)


def test_bounding_box_rejects_empty_size():
    with pytest.raises(ValueError, match="positive"):
        BoundingBox(0.1, 0.1, 0.0, 0.2)


def test_bounding_box_rejects_out_of_image_normalized_box():
    with pytest.raises(ValueError, match="origin"):
        BoundingBox(-0.1, 0.1, 0.2, 0.2)
    with pytest.raises(ValueError, match="past the image"):
        BoundingBox(0.9, 0.1, 0.2, 0.2)


def test_bounding_box_converts_to_pixels_and_back():
    box = BoundingBox(0.25, 0.5, 0.5, 0.25)
    pixels = box.to_pixels((640, 480))
    assert (pixels.x, pixels.y, pixels.w, pixels.h) == (160, 240, 320, 120)
    assert pixels.normalized is False
    round_trip = pixels.to_normalized((640, 480))
    assert (round_trip.x, round_trip.y) == pytest.approx((0.25, 0.5))
    assert (round_trip.w, round_trip.h) == pytest.approx((0.5, 0.25))


def test_bounding_box_pixel_conversion_never_exceeds_frame():
    box = BoundingBox(0.99, 0.99, 0.01, 0.01)
    pixels = box.to_pixels((100, 100))
    assert pixels.x + pixels.w <= 100
    assert pixels.y + pixels.h <= 100


# -- Detection / results -----------------------------------------------------


def test_detection_confidence_may_be_none():
    detection = Detection(label="sports ball", box=BoundingBox(0.1, 0.1, 0.2, 0.2))
    assert detection.confidence is None


def test_detection_rejects_out_of_range_confidence():
    with pytest.raises(ValueError, match="confidence"):
        Detection(label="ball", box=BoundingBox(0.1, 0.1, 0.2, 0.2), confidence=1.5)


def test_detection_result_distinguishes_failure_from_empty():
    failed = DetectionResult(detector_name="x", kind=DetectorKind.OPENCV, error="boom")
    empty = DetectionResult(detector_name="x", kind=DetectorKind.OPENCV)
    assert failed.failed and not failed.found
    assert not empty.failed and not empty.found


def test_detection_result_age_is_never_negative():
    result = DetectionResult(
        detector_name="x", kind=DetectorKind.VLM, frame_timestamp=5.0, processed_at=4.0
    )
    assert result.age_seconds == 0.0


# -- Telemetry / commands ----------------------------------------------------


def test_telemetry_defaults_to_not_reported():
    telemetry = Telemetry()
    assert telemetry.battery_percent is None
    assert telemetry.height_cm is None


def test_telemetry_rejects_impossible_battery():
    with pytest.raises(ValueError, match="battery"):
        Telemetry(battery_percent=140)


@pytest.mark.parametrize(
    ("status", "acknowledged", "unknown"),
    [
        (CommandStatus.REJECTED, False, False),
        (CommandStatus.REQUESTED, False, True),
        (CommandStatus.SENT, True, False),
        (CommandStatus.CONFIRMED, True, False),
        (CommandStatus.FAILED, False, False),
        (CommandStatus.TIMEOUT, False, True),
    ],
)
def test_command_status_semantics(status, acknowledged, unknown):
    result = CommandResult(command="land", status=status)
    assert result.ok is acknowledged
    assert status.acknowledged is acknowledged
    assert status.outcome_unknown is unknown


def test_command_result_requires_a_command():
    with pytest.raises(ValueError, match="command"):
        CommandResult(command="", status=CommandStatus.SENT)
