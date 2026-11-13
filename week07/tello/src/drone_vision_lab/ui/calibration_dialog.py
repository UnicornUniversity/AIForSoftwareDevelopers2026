"""Colour calibration workflow for the OpenCV detector.

The instructor drags a box over the target, the dialog estimates an HSV range,
and sliders refine it while a mask preview updates. All image processing runs
on the thread pool through :class:`CallableRunner`; the dialog only renders the
results.

Nothing here assumes a "universal" green: the range always comes from the
current lighting and camera white balance.
"""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..adapters.vision import (
    HsvRange,
    OpenCvDetectorConfig,
    OpenCvProcessing,
    OpenCvTargetDetector,
    auto_estimate_hsv_range,
    estimate_hsv_range,
)
from ..container import AppServices
from ..domain import DetectorKind, Frame
from ..errors import ConfigurationError
from ..state import SafetyState
from ..workers.runner import CallableRunner
from . import widgets
from .profile_store import store_profile_section, utc_timestamp
from .selection_view import SelectionVideoView

__all__ = ["CalibrationDialog"]

_log = logging.getLogger(__name__)

_PREVIEW_DELAY_MS = 80


def mask_to_qimage(mask: np.ndarray) -> QImage:
    height, width = mask.shape[:2]
    return QImage(
        mask.tobytes(), width, height, width, QImage.Format.Format_Grayscale8
    ).copy()


class CalibrationDialog(QDialog):
    def __init__(self, services: AppServices, frame: Frame, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Colour calibration — OpenCV")
        widgets.fit_initial_size(self, 900, 560, factor=0.8)
        self._services = services
        self._frame = frame
        detector = services.detectors.get(DetectorKind.OPENCV)
        if not isinstance(detector, OpenCvTargetDetector):
            raise ConfigurationError(
                "OpenCV detector is not available",
                user_message="The OpenCV detector is not configured in this build.",
            )
        self._detector = detector
        self._runner = CallableRunner(self)
        self._runner.finished.connect(self._on_preview)
        self._runner.failed.connect(self._on_preview_failed)
        self._auto_runner = CallableRunner(self)
        self._auto_runner.finished.connect(self._on_auto_finished)
        self._auto_runner.failed.connect(self._on_auto_failed)
        self._auto_scope = "across the frame"
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_PREVIEW_DELAY_MS)
        self._debounce.timeout.connect(self._refresh_preview)

        self._build()
        self._load_initial_config()
        self._schedule_preview()

    # -- construction --------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        instructions = QLabel(
            "Quick start: drag a box over the target and press “Auto-calibrate” "
            "to search inside it, or press it without a box to search the whole "
            "image. “Sample selected area” uses every coloured pixel in the box. "
            "Then refine the sliders until the mask covers the object and little "
            "else."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        body = QHBoxLayout()
        self._view = SelectionVideoView("No frame available")
        self._view.show_frame(self._frame)
        body.addWidget(self._view, 2)

        mask_column = QVBoxLayout()
        mask_title = QLabel("Threshold mask")
        mask_title.setStyleSheet("font-weight: 600;")
        self._mask_view = QLabel("mask preview")
        self._mask_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mask_view.setMinimumSize(260, 170)
        self._mask_view.setStyleSheet(
            "QLabel { background-color: #101418; color: #9aa4b2;"
            " border: 1px solid #2b333d; border-radius: 6px; }"
        )
        mask_column.addWidget(mask_title)
        mask_column.addWidget(self._mask_view, 1)
        body.addLayout(mask_column, 1)
        layout.addLayout(body, 1)

        layout.addWidget(self._build_sliders())
        layout.addWidget(self._build_buttons())

        self._status = QLabel("No calibration yet")
        self._status.setStyleSheet("color: #5b6470;")
        layout.addWidget(self._status)

        # The live preview keeps its own line. It refreshes after every slider
        # move and would otherwise overwrite the "what did Auto-calibrate /
        # Sample actually use?" confirmation before the operator can read it.
        self._preview_status = QLabel("")
        self._preview_status.setStyleSheet("color: #5b6470;")
        layout.addWidget(self._preview_status)

    def _slider(self, minimum: int, maximum: int, value: int) -> tuple[QSlider, QLabel]:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        readout = QLabel(str(value))
        readout.setMinimumWidth(40)
        slider.valueChanged.connect(lambda v, label=readout: label.setText(str(v)))
        slider.valueChanged.connect(self._schedule_preview)
        return slider, readout

    def _slider_row(
        self, layout: QFormLayout, label: str, slider: QSlider, readout: QLabel
    ) -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(slider, 1)
        row_layout.addWidget(readout)
        layout.addRow(label, row)

    def _build_sliders(self) -> QWidget:
        group = QGroupBox("Thresholds")
        form = QFormLayout(group)

        self._h_low, self._h_low_readout = self._slider(0, 179, 40)
        self._h_high, self._h_high_readout = self._slider(0, 179, 90)
        self._s_low, self._s_low_readout = self._slider(0, 255, 80)
        self._s_high, self._s_high_readout = self._slider(0, 255, 255)
        self._v_low, self._v_low_readout = self._slider(0, 255, 60)
        self._v_high, self._v_high_readout = self._slider(0, 255, 255)

        self._slider_row(form, "Hue low", self._h_low, self._h_low_readout)
        self._slider_row(form, "Hue high", self._h_high, self._h_high_readout)
        self._slider_row(form, "Saturation low", self._s_low, self._s_low_readout)
        self._slider_row(form, "Saturation high", self._s_high, self._s_high_readout)
        self._slider_row(form, "Value low", self._v_low, self._v_low_readout)
        self._slider_row(form, "Value high", self._v_high, self._v_high_readout)

        self._min_area = QDoubleSpinBox()
        self._min_area.setRange(0.01, 20.0)
        self._min_area.setSingleStep(0.1)
        self._min_area.setDecimals(2)
        self._min_area.setSuffix(" % of frame")
        self._min_area.setValue(0.20)
        self._min_area.valueChanged.connect(self._schedule_preview)
        form.addRow("Minimum area", self._min_area)

        self._morph = QComboBox()
        for kernel in (0, 3, 5, 7):
            self._morph.addItem("off" if kernel == 0 else f"{kernel}×{kernel}", userData=kernel)
        self._morph.setCurrentIndex(1)
        self._morph.currentIndexChanged.connect(self._schedule_preview)
        form.addRow("Noise filter", self._morph)

        self._label_combo = QComboBox()
        for label in ("green_tennis_ball", "apple"):
            self._label_combo.addItem(label)
        form.addRow("Target label", self._label_combo)
        return group

    def _build_buttons(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        auto_button = QPushButton("Auto-calibrate")
        auto_button.setToolTip(
            "Find the largest strongly coloured object and set the thresholds "
            "automatically. If you have drawn a box, only that area is searched. "
            "Nothing is saved until you press Save."
        )
        auto_button.clicked.connect(self.auto_calibrate)
        layout.addWidget(auto_button)

        sample_button = QPushButton("Sample selected area")
        sample_button.clicked.connect(self.sample_selection)
        layout.addWidget(sample_button)

        reset_button = QPushButton("Clear selection")
        reset_button.clicked.connect(self._view.clear_selection)
        layout.addWidget(reset_button)
        layout.addStretch(1)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        return row

    # -- calibration ---------------------------------------------------------

    def _load_initial_config(self) -> None:
        config = self._detector.config
        if not config.ranges:
            return
        first = config.ranges[0]
        for slider, value in (
            (self._h_low, first.lower[0]),
            (self._h_high, first.upper[0]),
            (self._s_low, first.lower[1]),
            (self._s_high, first.upper[1]),
            (self._v_low, first.lower[2]),
            (self._v_high, first.upper[2]),
        ):
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
        self._min_area.setValue(config.min_area_fraction * 100.0)
        index = self._morph.findData(config.morph_close_kernel)
        if index >= 0:
            self._morph.setCurrentIndex(index)

    def current_config(self) -> OpenCvDetectorConfig:
        hsv = HsvRange(
            lower=(self._h_low.value(), self._s_low.value(), self._v_low.value()),
            upper=(self._h_high.value(), self._s_high.value(), self._v_high.value()),
        )
        kernel = int(self._morph.currentData() or 0)
        return OpenCvDetectorConfig(
            ranges=(hsv,),
            min_area_fraction=self._min_area.value() / 100.0,
            blur_kernel=5,
            morph_open_kernel=kernel,
            morph_close_kernel=kernel,
            label=self._label_combo.currentText(),
        )

    def sample_selection(self) -> bool:
        selection = self._view.selection
        if selection is None:
            widgets.show_error(
                self,
                "Calibration",
                "Select the target object in the image first, then sample again.",
            )
            return False
        try:
            estimated = estimate_hsv_range(self._frame.image, selection)
        except ConfigurationError as exc:
            widgets.show_error(self, "Calibration", exc)
            return False

        self._apply_range(estimated)
        self._status.setStyleSheet("color: #2f6f44;")
        self._status.setText(
            "Sampled the selected area. Check the mask, refine if needed, then press Save."
        )
        self._schedule_preview()
        return True

    def auto_calibrate(self) -> None:
        """Estimate thresholds from the largest coloured object, off the GUI thread.

        When the operator has drawn a box, only that area is searched, so a
        colourful background cannot win the "largest region" contest.
        """
        if self._auto_runner.busy:
            return
        selection = self._view.selection
        self._auto_scope = (
            "inside the selected area" if selection is not None else "across the frame"
        )
        self._status.setStyleSheet("color: #5b6470;")
        self._status.setText(f"Auto-calibrating {self._auto_scope}…")
        if not self._auto_runner.submit(
            lambda: auto_estimate_hsv_range(self._frame.image, region=selection)
        ):
            self._status.setText("Auto-calibration is already running.")

    def _on_auto_finished(self, result: object) -> None:
        if not isinstance(result, HsvRange):
            return
        self._apply_range(result)
        self._status.setStyleSheet("color: #2f6f44;")
        self._status.setText(
            f"Auto-calibrated {self._auto_scope}. Check the mask, refine if "
            "needed, then press Save."
        )
        self._schedule_preview()

    def _on_auto_failed(self, message: str) -> None:
        self._status.setStyleSheet("color: #a12a2a;")
        self._status.setText("Auto-calibration failed.")
        widgets.show_error(self, "Auto-calibration", message)

    def _apply_range(self, hsv_range: HsvRange) -> None:
        for slider, value in (
            (self._h_low, hsv_range.lower[0]),
            (self._h_high, hsv_range.upper[0]),
            (self._s_low, hsv_range.lower[1]),
            (self._s_high, hsv_range.upper[1]),
            (self._v_low, hsv_range.lower[2]),
            (self._v_high, hsv_range.upper[2]),
        ):
            slider.setValue(value)

    def save(self) -> None:
        config = self.current_config()
        self._detector.update_config(config)
        if not self._detector.ready:
            try:
                self._detector.load()
            except Exception as exc:  # noqa: BLE001
                widgets.show_error(self, "Calibration", exc)
                return
        try:
            self._store_profile(config)
        except Exception as exc:  # noqa: BLE001 - reported, the dialog stays open
            widgets.show_error(self, "Calibration", exc)
            return
        self._services.state.update(safety_state=SafetyState.CALIBRATED, last_error=None)
        _log.info(
            "Colour calibration saved",
            extra={
                "context": {
                    "label": config.label,
                    "ranges": len(config.ranges),
                    "min_area": config.min_area_fraction,
                }
            },
        )
        self.accept()

    def _store_profile(self, config: OpenCvDetectorConfig) -> None:
        store_profile_section(
            self._services,
            "opencv",
            config.to_dict(),
            extra={
                "calibration": {
                    "label": config.label,
                    "ranges": len(config.ranges),
                    "saved_at": utc_timestamp(),
                }
            },
        )

    # -- preview -------------------------------------------------------------

    def _schedule_preview(self) -> None:
        self._debounce.start()

    def _refresh_preview(self) -> None:
        config = self.current_config()
        detector = OpenCvTargetDetector(config)
        try:
            detector.load()
        except Exception as exc:  # noqa: BLE001
            self._preview_status.setText(str(exc))
            return
        frame = self._frame
        self._runner.submit(lambda: detector.process(frame))

    def _on_preview(self, processing: object) -> None:
        if not isinstance(processing, OpenCvProcessing):
            return
        pixmap = QPixmap.fromImage(mask_to_qimage(processing.mask))
        self._mask_view.setPixmap(
            pixmap.scaled(
                self._mask_view.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        result = processing.result
        if result.failed:
            self._preview_status.setText(f"Preview failed: {result.error}")
            return
        count = len(result.detections)
        detail = ""
        if count:
            area = result.detections[0].metrics.get("mask_area_px", 0.0)
            detail = f" — largest contour {area:,.0f} px"
        self._preview_status.setText(f"{count} candidate(s) in preview{detail}")

    def _on_preview_failed(self, message: str) -> None:
        self._preview_status.setText(f"Preview failed: {message}")
