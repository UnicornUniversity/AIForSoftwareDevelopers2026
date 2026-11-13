"""Calibration dialog: sampling, saving and profile persistence."""

from __future__ import annotations

import time

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from drone_vision_lab.adapters.vision import HsvRange, OpenCvTargetDetector  # noqa: E402
from drone_vision_lab.domain import DetectorKind, Frame  # noqa: E402
from drone_vision_lab.state import SafetyState  # noqa: E402
from drone_vision_lab.ui.calibration_dialog import CalibrationDialog  # noqa: E402


def _green_frame(rect=(100, 70, 80, 80)) -> Frame:
    image = np.full((240, 320, 3), 30, dtype=np.uint8)
    x, y, w, h = rect
    patch = np.full((h, w, 3), (60, 200, 200), dtype=np.uint8)
    image[y : y + h, x : x + w] = cv2.cvtColor(patch, cv2.COLOR_HSV2BGR)
    return Frame(image=image, captured_at=time.monotonic(), source_id="test", index=0)


def _grey_frame() -> Frame:
    image = np.full((240, 320, 3), 30, dtype=np.uint8)
    return Frame(image=image, captured_at=time.monotonic(), source_id="test", index=0)


def _two_object_frame() -> Frame:
    """A large red background object and a smaller green target."""
    image = np.full((240, 320, 3), 30, dtype=np.uint8)
    image[20:180, 20:180] = cv2.cvtColor(
        np.full((160, 160, 3), (0, 200, 200), dtype=np.uint8), cv2.COLOR_HSV2BGR
    )
    image[60:120, 200:260] = cv2.cvtColor(
        np.full((60, 60, 3), (60, 200, 200), dtype=np.uint8), cv2.COLOR_HSV2BGR
    )
    return Frame(image=image, captured_at=time.monotonic(), source_id="test", index=0)


def _contains_hue(hsv_range: HsvRange, hue: int) -> bool:
    low, high = hsv_range.lower[0], hsv_range.upper[0]
    if low <= high:
        return low <= hue <= high
    return hue >= low or hue <= high


def _wait_until(qapp, predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return predicate()


def test_sampling_a_selection_estimates_bounds(qapp, services):
    dialog = CalibrationDialog(services, _green_frame())
    dialog._view.set_selection((100, 70, 80, 80))  # noqa: SLF001

    assert dialog.sample_selection() is True
    assert dialog._status.text().startswith("Sampled the selected area")  # noqa: SLF001
    config = dialog.current_config()
    assert config.calibrated
    assert config.ranges[0].lower[1] <= 200 <= config.ranges[0].upper[1]


def test_sampling_without_a_selection_is_refused(qapp, services, monkeypatch):
    dialog = CalibrationDialog(services, _green_frame())
    shown: list[str] = []
    monkeypatch.setattr(
        "drone_vision_lab.ui.calibration_dialog.widgets.show_error",
        lambda _parent, title, _error: shown.append(title),
    )

    assert dialog.sample_selection() is False
    assert shown == ["Calibration"]


def test_save_persists_a_versioned_profile_and_advances_state(qapp, services):
    detector = services.detectors[DetectorKind.OPENCV]
    assert isinstance(detector, OpenCvTargetDetector)
    dialog = CalibrationDialog(services, _green_frame())
    dialog._view.set_selection((100, 70, 80, 80))  # noqa: SLF001
    dialog.sample_selection()

    dialog.save()

    assert detector.config.calibrated is True
    profile = services.profiles.get("default")
    assert profile is not None
    assert profile.payload["opencv"]["schema_version"] == 1
    assert services.state.snapshot().safety_state is SafetyState.CALIBRATED


def test_auto_calibrate_sets_the_thresholds_from_the_largest_object(qapp, services):
    dialog = CalibrationDialog(services, _green_frame())
    assert dialog._h_low.value() == 40  # noqa: SLF001 - the built-in default

    dialog.auto_calibrate()

    assert _wait_until(
        qapp, lambda: dialog._status.text().startswith("Auto-calibrated across")  # noqa: SLF001
    )
    config = dialog.current_config()
    assert config.ranges[0].lower[0] <= 60 <= config.ranges[0].upper[0]


def test_auto_calibrate_reports_a_frame_without_a_coloured_object(qapp, services, monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(
        "drone_vision_lab.ui.calibration_dialog.widgets.show_error",
        lambda _parent, title, _error: shown.append(title),
    )
    dialog = CalibrationDialog(services, _grey_frame())

    dialog.auto_calibrate()

    assert _wait_until(qapp, lambda: shown == ["Auto-calibration"])


def test_auto_calibrate_searches_inside_the_drawn_selection(qapp, services):
    dialog = CalibrationDialog(services, _two_object_frame())

    dialog.auto_calibrate()  # no box: the large red "background" object wins
    assert _wait_until(
        qapp, lambda: dialog._status.text().startswith("Auto-calibrated across")  # noqa: SLF001
    )
    assert _contains_hue(dialog.current_config().ranges[0], 0)
    assert not _contains_hue(dialog.current_config().ranges[0], 60)

    dialog._view.set_selection((190, 50, 80, 80))  # noqa: SLF001 - box on the target
    dialog.auto_calibrate()
    assert _wait_until(
        qapp,
        lambda: dialog._status.text().startswith(  # noqa: SLF001
            "Auto-calibrated inside the selected area"
        ),
    )
    assert _contains_hue(dialog.current_config().ranges[0], 60)
    assert not _contains_hue(dialog.current_config().ranges[0], 0)


def test_the_preview_status_does_not_overwrite_the_auto_result(qapp, services):
    dialog = CalibrationDialog(services, _green_frame())

    dialog.auto_calibrate()
    assert _wait_until(
        qapp, lambda: dialog._status.text().startswith("Auto-calibrated")  # noqa: SLF001
    )

    # The debounced preview finishes after the auto result; it must use its own
    # line so the operator can still read which scope was searched.
    assert _wait_until(
        qapp, lambda: "candidate" in dialog._preview_status.text()  # noqa: SLF001
    )
    assert dialog._status.text().startswith("Auto-calibrated")  # noqa: SLF001


def test_current_config_reflects_sliders(qapp, services):
    dialog = CalibrationDialog(services, _green_frame())
    dialog._h_low.setValue(30)  # noqa: SLF001
    dialog._h_high.setValue(70)  # noqa: SLF001
    dialog._min_area.setValue(0.5)  # noqa: SLF001

    config = dialog.current_config()
    assert config.ranges[0].lower[0] == 30
    assert config.ranges[0].upper[0] == 70
    assert config.min_area_fraction == pytest.approx(0.005)
