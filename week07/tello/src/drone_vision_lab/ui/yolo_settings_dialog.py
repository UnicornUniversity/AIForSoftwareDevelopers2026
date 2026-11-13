"""YOLO model selection, loading and a test run on the current frame.

Loading a checkpoint and running inference can both take seconds, so both go
through :class:`CallableRunner`. The dialog never blocks the GUI thread and
never downloads weights on its own: the download button asks for confirmation
first and names the source and licence of the weights.

The loaded model is staged locally and only handed to the application on Save,
so Cancel really cancels.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..adapters.optional import require_ultralytics
from ..adapters.vision import YoloDetector, YoloDetectorConfig
from ..container import AppServices
from ..domain import DetectionResult, DetectorKind, Frame
from ..workers.runner import CallableRunner
from . import widgets
from .profile_store import store_profile_section

__all__ = ["YoloSettingsDialog"]

_log = logging.getLogger(__name__)

_OFFICIAL_WEIGHTS = "yolo11n.pt"
_APP_ROOT = Path(__file__).resolve().parents[3]
_PREFERRED_WEIGHTS = ("yolo11n.pt", "yolo11m.pt")
_WEIGHTS_DIRS = ("", "models", "weights")


def _discover_weights(root: Path) -> Path | None:
    """Return a local YOLO checkpoint under ``root``, preferring small models."""
    candidates: list[Path] = []
    for name in _WEIGHTS_DIRS:
        directory = root / name if name else root
        if directory.is_dir():
            candidates.extend(path for path in directory.glob("*.pt") if path.is_file())
    if not candidates:
        return None
    by_name: dict[str, Path] = {}
    for path in candidates:
        by_name.setdefault(path.name.casefold(), path)
    for preferred in _PREFERRED_WEIGHTS:
        found = by_name.get(preferred.casefold())
        if found is not None:
            return found
    return min(candidates, key=lambda path: path.name.casefold())


class YoloSettingsDialog(QDialog):
    def __init__(
        self,
        services: AppServices,
        frame: Frame | None,
        parent: QWidget | None = None,
        *,
        detector_factory: Callable[[YoloDetectorConfig], YoloDetector] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("YOLO detector settings")
        widgets.fit_initial_size(self, 640, 420, factor=0.85)
        self._services = services
        self._frame = frame
        self._factory = detector_factory or YoloDetector
        existing = services.detectors.get(DetectorKind.YOLO)
        self._detector: YoloDetector | None = (
            existing if isinstance(existing, YoloDetector) and existing.ready else None
        )
        self._runner = CallableRunner(self)
        self._runner.finished.connect(self._on_finished)
        self._runner.failed.connect(self._on_failed)
        self._pending = ""

        self._build()
        if self._detector is not None:
            self._apply_loaded_state()

    # -- construction --------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        note = QLabel(
            "Pick a local .pt weights file. The application never downloads weights "
            "without your explicit confirmation, and a downloaded model is the "
            "Ultralytics release asset, licensed AGPL-3.0."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #5b6470;")
        layout.addWidget(note)

        form = QFormLayout()

        path_row = QWidget()
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        self._path_edit = QLineEdit(self._initial_path())
        self._path_edit.setPlaceholderText(r"C:\models\yolo11n.pt")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        path_layout.addWidget(self._path_edit, 1)
        path_layout.addWidget(browse)
        form.addRow("Weights file", path_row)

        self._class_combo = QComboBox()
        self._class_combo.setEnabled(False)
        self._class_combo.setToolTip("Classes come from the loaded model's own metadata.")
        form.addRow("Target class", self._class_combo)

        self._confidence = QDoubleSpinBox()
        self._confidence.setRange(0.05, 0.95)
        self._confidence.setSingleStep(0.05)
        self._confidence.setDecimals(2)
        self._confidence.setValue(self._initial_confidence())
        form.addRow("Confidence threshold", self._confidence)

        self._device_label = QLabel("Device: not loaded")
        self._device_label.setStyleSheet("color: #5b6470;")
        form.addRow("", self._device_label)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        self._load_button = QPushButton("Load model")
        self._load_button.clicked.connect(self.load_model)
        self._download_button = QPushButton("Download YOLO11n weights…")
        self._download_button.setToolTip(
            "Downloads yolo11n.pt from the Ultralytics release assets after confirmation."
        )
        self._download_button.clicked.connect(self._confirm_download)
        self._test_button = QPushButton("Detect in current frame")
        self._test_button.setEnabled(False)
        self._test_button.clicked.connect(self.test_on_frame)
        buttons.addWidget(self._load_button)
        buttons.addWidget(self._download_button)
        buttons.addWidget(self._test_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._status = QLabel("No model loaded")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #5b6470;")
        layout.addWidget(self._status)
        layout.addStretch(1)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def _initial_config(self) -> YoloDetectorConfig:
        detector = self._detector
        return detector.config if detector is not None else YoloDetectorConfig()

    def _initial_path(self) -> str:
        configured = self._initial_config().model_path.strip()
        if configured:
            return configured
        found = _discover_weights(_APP_ROOT)
        if found is not None:
            return str(found)
        return str(_APP_ROOT / _OFFICIAL_WEIGHTS)

    def _initial_confidence(self) -> float:
        return self._initial_config().confidence_threshold

    # -- loading -------------------------------------------------------------

    def current_config(self) -> YoloDetectorConfig:
        label = self._class_combo.currentText() or self._initial_config().class_label
        return YoloDetectorConfig(
            model_path=self._path_edit.text().strip(),
            class_label=label,
            confidence_threshold=self._confidence.value(),
            iou_threshold=self._initial_config().iou_threshold,
            max_detections=self._initial_config().max_detections,
            device=self._initial_config().device,
        )

    def load_model(self) -> bool:
        try:
            config = self.current_config()
        except ValueError as exc:
            widgets.show_error(self, "YOLO", str(exc))
            return False
        self._status.setText("Loading model…")
        self._pending = "load"
        return self._runner.submit(lambda: self._stage(config))

    def _stage(self, config: YoloDetectorConfig) -> YoloDetector:
        """Create and load the model; runs on the worker thread."""
        detector = self._factory(config)
        detector.load()
        return detector

    def _on_finished(self, result: object) -> None:
        if self._pending == "load" and isinstance(result, YoloDetector):
            self._on_model_loaded(result)
        elif self._pending == "test" and isinstance(result, DetectionResult):
            self._on_test_finished(result)
        elif self._pending == "download":
            self._on_download_finished(result)

    def _on_failed(self, message: str) -> None:
        if self._pending == "download":
            self._status.setText(f"Download failed: {message}")
        elif self._pending == "test":
            self._status.setText(f"Detection failed: {message}")
        else:
            self._status.setText(f"Model could not be loaded: {message}")
            widgets.show_error(self, "YOLO", message)

    def _on_model_loaded(self, detector: YoloDetector) -> None:
        self._detector = detector
        self._apply_loaded_state()
        classes = detector.available_classes
        self._status.setText(
            f"Loaded {len(classes)} classes on {detector.device}. "
            f"{detector.device_note}"
        )
        _log.info(
            "YOLO model loaded",
            extra={
                "context": {
                    "model": Path(detector.config.model_path).name,
                    "classes": len(classes),
                    "device": detector.device,
                }
            },
        )

    def _apply_loaded_state(self) -> None:
        detector = self._detector
        if detector is None:
            return
        previous = self._class_combo.currentText() or detector.config.class_label
        self._class_combo.blockSignals(True)
        self._class_combo.clear()
        for _class_id, name in sorted(
            detector.available_classes, key=lambda item: item[1].casefold()
        ):
            self._class_combo.addItem(name)
        index = self._class_combo.findText(previous)
        preferred = self._class_combo.findText("apple")
        self._class_combo.setCurrentIndex(index if index >= 0 else max(preferred, 0))
        self._class_combo.blockSignals(False)
        self._class_combo.setEnabled(True)
        self._confidence.setValue(detector.config.confidence_threshold)
        self._device_label.setText(f"Device: {detector.device} — {detector.device_note}")
        self._test_button.setEnabled(self._frame is not None)

    # -- test run ------------------------------------------------------------

    def test_on_frame(self) -> bool:
        detector = self._detector
        frame = self._frame
        if detector is None or frame is None:
            return False
        config = self.current_config()
        detector.update_config(config)
        self._status.setText("Running inference…")
        self._pending = "test"
        return self._runner.submit(lambda: detector.detect(frame))

    def _on_test_finished(self, result: DetectionResult) -> None:
        if result.failed:
            self._status.setText(f"Detection failed: {result.error}")
            return
        latency = f"{result.latency_ms:.0f} ms" if result.latency_ms is not None else "unknown time"
        if not result.detections:
            self._status.setText(f"No target found in this frame — {latency}")
            return
        best = max(
            result.detections,
            key=lambda d: d.confidence if d.confidence is not None else -1.0,
        )
        confidence = f"{best.confidence:.2f}" if best.confidence is not None else "n/a"
        self._status.setText(
            f"{len(result.detections)} detection(s) — {latency} — best: "
            f"{best.label}, confidence {confidence}"
        )

    # -- download ------------------------------------------------------------

    def _confirm_download(self) -> None:
        answer = QMessageBox.question(
            self,
            "Download YOLO11n weights?",
            "This downloads the official Ultralytics YOLO11n checkpoint "
            f"({_OFFICIAL_WEIGHTS}) from the Ultralytics release assets into the "
            "current working directory.\n\n"
            "Ultralytics models are licensed AGPL-3.0. Check that this licence is "
            "acceptable for your use before continuing.\n\n"
            "Download now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if not widgets.is_yes(answer):
            return
        self._status.setText("Downloading weights…")
        self._pending = "download"
        self._runner.submit(self._download_weights)

    def _download_weights(self) -> str:
        """Explicit download path; never called without operator confirmation."""
        ultralytics = require_ultralytics()
        model = ultralytics.YOLO(_OFFICIAL_WEIGHTS)
        resolved = getattr(model, "ckpt_path", None) or _OFFICIAL_WEIGHTS
        return str(Path(resolved).resolve())

    def _on_download_finished(self, result: object) -> None:
        if isinstance(result, str) and Path(result).is_file():
            self._path_edit.setText(result)
            self._status.setText("Weights downloaded. Press “Load model” to use them.")
        else:
            self._status.setText("The download did not produce a weights file.")

    # -- save ----------------------------------------------------------------

    def save(self) -> None:
        detector = self._detector
        if detector is None:
            widgets.show_error(
                self,
                "YOLO",
                "Load a model successfully before saving these settings.",
            )
            return
        config = self.current_config()
        detector.update_config(config)
        self._services.detectors[DetectorKind.YOLO] = detector
        # The detector is live now, even if storing the profile fails below.
        # Every tab that gates on the YOLO slot re-reads it from this signal.
        self._services.detector_events.publish(DetectorKind.YOLO)
        try:
            self._store_profile(config)
        except Exception as exc:  # noqa: BLE001 - reported, the dialog stays open
            widgets.show_error(self, "YOLO", exc)
            return
        _log.info(
            "YOLO settings saved",
            extra={
                "context": {
                    "model": Path(config.model_path).name,
                    "class": config.class_label,
                    "confidence": config.confidence_threshold,
                }
            },
        )
        self.accept()

    def _store_profile(self, config: YoloDetectorConfig) -> None:
        store_profile_section(self._services, "yolo", config.to_dict())

    # -- helpers -------------------------------------------------------------

    def _browse(self) -> None:
        text = self._path_edit.text().strip()
        current = Path(text) if text else None
        if current is not None and current.parent.is_dir():
            start = str(current.parent)
        elif _APP_ROOT.is_dir():
            start = str(_APP_ROOT)
        else:
            start = str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select YOLO weights",
            start,
            "PyTorch checkpoints (*.pt);;All files (*)",
        )
        if path:
            self._path_edit.setText(path)

    # -- accessors used by tests --------------------------------------------

    @property
    def detector(self) -> YoloDetector | None:
        """The staged detector; equals the installed one only after Save."""
        return self._detector

    @property
    def model_path_edit(self) -> QLineEdit:
        return self._path_edit

    @property
    def class_combo(self) -> QComboBox:
        return self._class_combo

    @property
    def device_label(self) -> QLabel:
        return self._device_label

    @property
    def status_label(self) -> QLabel:
        return self._status

    @property
    def load_button(self) -> QPushButton:
        return self._load_button

    @property
    def test_button(self) -> QPushButton:
        return self._test_button
