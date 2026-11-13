"""OpenCV detector and calibration on synthetic images."""

from __future__ import annotations

import time

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from drone_vision_lab.adapters.vision.opencv_calibration import (  # noqa: E402
    auto_estimate_hsv_range,
    estimate_hsv_range,
    sample_patch_statistics,
)
from drone_vision_lab.adapters.vision.opencv_detector import (  # noqa: E402
    HsvRange,
    OpenCvDetectorConfig,
    OpenCvTargetDetector,
    build_mask,
    contours_to_detections,
)
from drone_vision_lab.domain import Frame  # noqa: E402
from drone_vision_lab.errors import ConfigurationError  # noqa: E402

GREEN = HsvRange((50, 120, 100), (70, 255, 255))


def _frame(width: int = 320, height: int = 240) -> Frame:
    image = np.full((height, width, 3), 30, dtype=np.uint8)
    return Frame(image=image, captured_at=time.monotonic(), source_id="synthetic", index=0)


def _paint(frame: Frame, rect: tuple[int, int, int, int], hue: int = 60) -> Frame:
    """Paint a filled rectangle of the given HSV hue onto a copy of the frame."""
    image = frame.image.copy()
    x, y, w, h = rect
    patch = np.full((h, w, 3), (hue, 200, 200), dtype=np.uint8)
    image[y : y + h, x : x + w] = cv2.cvtColor(patch, cv2.COLOR_HSV2BGR)
    return Frame(image=image, captured_at=frame.captured_at, source_id="synthetic", index=0)


def _contains_hue(hsv_range: HsvRange, hue: int) -> bool:
    low, high = hsv_range.lower[0], hsv_range.upper[0]
    if low <= high:
        return low <= hue <= high
    return hue >= low or hue <= high


def _detector(config: OpenCvDetectorConfig | None = None) -> OpenCvTargetDetector:
    detector = OpenCvTargetDetector(
        config
        or OpenCvDetectorConfig(ranges=(GREEN,), blur_kernel=0, morph_close_kernel=0)
    )
    detector.load()
    return detector


# -- config ------------------------------------------------------------------


def test_hsv_range_rejects_out_of_range_values():
    with pytest.raises(ValueError):
        HsvRange((200, 0, 0), (250, 255, 255))
    with pytest.raises(ValueError):
        HsvRange((10, 0, 0), (20, 300, 255))


def test_hsv_range_reports_wraparound():
    assert HsvRange((165, 100, 100), (10, 255, 255)).wraps
    assert not GREEN.wraps


def test_config_round_trip():
    config = OpenCvDetectorConfig(ranges=(GREEN,), label="apple", min_area_fraction=0.01)
    restored = OpenCvDetectorConfig.from_dict(config.to_dict())
    assert restored == config


def test_config_rejects_unknown_schema_version():
    config = OpenCvDetectorConfig(ranges=(GREEN,)).to_dict()
    config["schema_version"] = 99
    with pytest.raises(ConfigurationError):
        OpenCvDetectorConfig.from_dict(config)


def test_config_rejects_even_kernel():
    with pytest.raises(ValueError):
        OpenCvDetectorConfig(ranges=(GREEN,), blur_kernel=4)


# -- detection ---------------------------------------------------------------


def test_detects_the_painted_object():
    frame = _paint(_frame(), (100, 70, 80, 80))
    result = _detector().detect(frame)

    assert not result.failed
    assert len(result.detections) == 1
    detection = result.detections[0]
    assert detection.label == "green_tennis_ball"
    assert detection.box.x == pytest.approx(100 / 320, abs=0.01)
    assert detection.box.y == pytest.approx(70 / 240, abs=0.01)
    assert detection.box.w == pytest.approx(80 / 320, abs=0.01)


def test_thresholding_produces_no_confidence():
    frame = _paint(_frame(), (100, 70, 80, 80))
    detection = _detector().detect(frame).detections[0]
    assert detection.confidence is None
    assert "fill_ratio" in detection.metrics


def test_empty_scene_yields_no_detections_without_error():
    result = _detector().detect(_frame())
    assert result.failed is False
    assert result.detections == ()
    assert result.found is False


def test_max_detections_keeps_the_largest_candidates():
    frame = _paint(_frame(), (10, 10, 30, 30))
    frame = _paint(frame, (100, 10, 90, 90))
    frame = _paint(frame, (220, 150, 60, 60))
    config = OpenCvDetectorConfig(
        ranges=(GREEN,),
        blur_kernel=0,
        morph_close_kernel=0,
        min_area_fraction=0.0005,
        max_detections=2,
    )
    result = _detector(config).detect(frame)
    assert len(result.detections) == 2
    areas = [d.metrics["mask_area_px"] for d in result.detections]
    assert areas == sorted(areas, reverse=True)


def test_noise_specks_below_min_area_are_ignored():
    frame = _frame()
    image = frame.image.copy()
    for x in range(5, 300, 17):
        for y in range(5, 220, 19):
            image[y : y + 2, x : x + 2] = (60, 210, 200)
    noisy = Frame(image, frame.captured_at, "synthetic", 0)
    config = OpenCvDetectorConfig(ranges=(GREEN,), blur_kernel=0, min_area_fraction=0.01)
    assert _detector(config).detect(noisy).detections == ()


def test_morphology_removes_small_specks_next_to_the_object():
    frame = _paint(_frame(), (100, 80, 70, 70))
    image = frame.image.copy()
    image[10:14, 10:14] = (60, 210, 200)
    noisy = Frame(image, frame.captured_at, "synthetic", 0)
    config = OpenCvDetectorConfig(
        ranges=(GREEN,),
        blur_kernel=0,
        morph_open_kernel=5,
        min_area_fraction=0.0001,
    )
    detections = _detector(config).detect(noisy).detections
    assert len(detections) == 1
    assert detections[0].box.area > 0.01


def test_hue_wraparound_detects_both_sides_of_red():
    frame = _paint(_frame(), (20, 20, 50, 50), hue=175)
    frame = _paint(frame, (200, 120, 50, 50), hue=5)
    config = OpenCvDetectorConfig(
        ranges=(HsvRange((165, 100, 100), (10, 255, 255)),),
        blur_kernel=0,
        morph_close_kernel=0,
        min_area_fraction=0.001,
    )
    detections = _detector(config).detect(frame).detections
    assert len(detections) == 2


def test_multiple_ranges_are_combined():
    frame = _paint(_frame(), (20, 20, 50, 50), hue=60)
    frame = _paint(frame, (200, 120, 50, 50), hue=120)
    config = OpenCvDetectorConfig(
        ranges=(GREEN, HsvRange((110, 120, 100), (130, 255, 255))),
        blur_kernel=0,
        morph_close_kernel=0,
        min_area_fraction=0.001,
    )
    assert len(_detector(config).detect(frame).detections) == 2


def test_uncalibrated_detector_reports_an_error():
    detector = OpenCvTargetDetector()
    detector.load()
    result = detector.detect(_frame())
    assert result.failed
    assert "calibration" in (result.error or "").lower()


def test_unloaded_detector_reports_an_error():
    detector = OpenCvTargetDetector(OpenCvDetectorConfig(ranges=(GREEN,)))
    assert detector.ready is False
    result = detector.detect(_frame())
    assert result.failed


def test_process_returns_the_mask_for_preview():
    frame = _paint(_frame(), (100, 70, 80, 80))
    processing = _detector().process(frame)
    assert processing.mask.shape == (240, 320)
    assert all(processing.mask[y, x] == 255 for y, x in [(110, 140), (140, 140)])


def test_build_mask_without_ranges_is_empty():
    mask = build_mask(_paint(_frame(), (10, 10, 20, 20)), OpenCvDetectorConfig())
    assert mask.sum() == 0


def test_contours_to_detections_ignores_zero_area():
    mask = np.zeros((100, 100), dtype=np.uint8)
    assert contours_to_detections(mask, OpenCvDetectorConfig(ranges=(GREEN,))) == ()


# -- calibration -------------------------------------------------------------


def test_estimate_range_from_a_painted_patch_detects_the_object():
    frame = _paint(_frame(), (100, 70, 80, 80), hue=60)
    estimated = estimate_hsv_range(frame.image, (100, 70, 80, 80))

    assert estimated.lower[1] <= 200 <= estimated.upper[1]
    config = OpenCvDetectorConfig(
        ranges=(estimated,), blur_kernel=0, morph_close_kernel=0, min_area_fraction=0.001
    )
    assert len(_detector(config).detect(frame).detections) == 1


def test_estimate_range_survives_hue_wraparound():
    frame = _paint(_frame(), (100, 70, 80, 80), hue=178)
    estimated = estimate_hsv_range(frame.image, (100, 70, 80, 80))
    config = OpenCvDetectorConfig(
        ranges=(estimated,), blur_kernel=0, morph_close_kernel=0, min_area_fraction=0.001
    )
    assert len(_detector(config).detect(frame).detections) == 1


def test_estimate_range_rejects_a_colourless_region():
    frame = _frame()  # uniform grey: no saturated pixels
    with pytest.raises(ConfigurationError):
        estimate_hsv_range(frame.image, (10, 10, 100, 100))


def test_auto_estimate_finds_the_coloured_object_without_a_selection():
    frame = _paint(_frame(), (100, 70, 80, 80), hue=178)

    estimated = auto_estimate_hsv_range(frame.image)

    config = OpenCvDetectorConfig(
        ranges=(estimated,), blur_kernel=0, morph_close_kernel=0, min_area_fraction=0.001
    )
    assert len(_detector(config).detect(frame).detections) == 1


def test_auto_estimate_uses_the_largest_coloured_region():
    frame = _paint(_frame(), (20, 20, 30, 30), hue=0)  # small red object
    frame = _paint(frame, (150, 60, 120, 120), hue=60)  # larger green object

    estimated = auto_estimate_hsv_range(frame.image)

    assert estimated.lower[0] <= 60 <= estimated.upper[0]
    assert not (estimated.lower[0] <= 0 <= estimated.upper[0])


def test_auto_estimate_rejects_a_colourless_image():
    with pytest.raises(ConfigurationError):
        auto_estimate_hsv_range(_frame().image)


def test_auto_estimate_rejects_only_tiny_coloured_specks():
    frame = _paint(_frame(), (10, 10, 3, 3), hue=60)
    with pytest.raises(ConfigurationError):
        auto_estimate_hsv_range(frame.image)


def test_auto_estimate_can_search_only_the_selected_region():
    frame = _paint(_frame(), (20, 20, 160, 160), hue=0)  # large red background object
    frame = _paint(frame, (200, 60, 60, 60), hue=60)  # smaller green target

    whole_frame = auto_estimate_hsv_range(frame.image)
    inside_box = auto_estimate_hsv_range(frame.image, region=(190, 50, 80, 80))

    assert _contains_hue(whole_frame, 0)  # red is the largest region
    assert not _contains_hue(whole_frame, 60)
    assert _contains_hue(inside_box, 60)  # the box makes green the winner
    assert not _contains_hue(inside_box, 0)


def test_auto_estimate_minimum_area_is_relative_to_the_selection():
    frame = _paint(_frame(), (100, 70, 10, 10), hue=60)  # 100 px, below 0.2 % of the frame

    with pytest.raises(ConfigurationError):
        auto_estimate_hsv_range(frame.image)

    estimated = auto_estimate_hsv_range(frame.image, region=(90, 60, 40, 40))
    assert _contains_hue(estimated, 60)


def test_auto_estimate_rejects_an_empty_selection():
    with pytest.raises(ConfigurationError):
        auto_estimate_hsv_range(_frame().image, region=(10, 10, 0, 0))


def test_estimate_range_rejects_an_empty_selection():
    with pytest.raises(ConfigurationError):
        estimate_hsv_range(_frame().image, (10, 10, 0, 0))
    with pytest.raises(ConfigurationError):
        sample_patch_statistics(_frame().image, (10, 10, 0, 0))
