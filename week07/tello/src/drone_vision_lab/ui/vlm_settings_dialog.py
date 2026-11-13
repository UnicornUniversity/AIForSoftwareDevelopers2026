"""VLM settings and periodic analysis.

Everything that talks to Ollama runs on the thread pool. The dialog shows the
model, latency, the age of the source frame and the age of the displayed
result, and marks a result stale when it is older than a few intervals — a VLM
answer must never look fresher than it is.

VLM output is advisory. Nothing here, and nothing it saves, can command the
aircraft.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..adapters.vlm import (
    DEFAULT_PROMPT,
    OllamaClient,
    OllamaModel,
    OllamaVlmDetector,
    VlmConfig,
)
from ..container import AppServices
from ..domain import DetectionResult, DetectorKind, Frame
from ..workers.runner import CallableRunner
from ..workers.vlm_poller import VlmPoller
from . import widgets
from .profile_store import store_profile_section

__all__ = ["VlmSettingsDialog"]

_log = logging.getLogger(__name__)

_STALE_FLOOR_S = 3.0

#: The first ``"label": "..."`` value in the prompt template.
_LABEL_FIELD = re.compile(r'("label"\s*:\s*)"[^"]*"')


class VlmSettingsDialog(QDialog):
    def __init__(
        self,
        services: AppServices,
        frame: Frame | None,
        parent: QWidget | None = None,
        *,
        frame_provider: Callable[[], Frame | None] | None = None,
        client_factory: Callable[[str], OllamaClient] | None = None,
        detector_factory: Callable[..., OllamaVlmDetector] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("VLM analysis — Ollama")
        widgets.fit_initial_size(self, 760, 620, factor=0.85)
        self._services = services
        self._frame = frame
        self._frame_provider = frame_provider or (lambda: self._frame)
        self._client_factory = client_factory or OllamaClient
        self._detector_factory = detector_factory or OllamaVlmDetector
        existing = services.detectors.get(DetectorKind.VLM)
        self._detector: OllamaVlmDetector | None = (
            existing if isinstance(existing, OllamaVlmDetector) and existing.ready else None
        )
        # A recovered profile installs a detector with saved settings but no
        # client. Show those settings so the operator does not retype them, and
        # still require Check service + Load model before use.
        self._staged_config: VlmConfig | None = (
            existing.config
            if isinstance(existing, OllamaVlmDetector) and self._detector is None
            else None
        )
        self._client: OllamaClient | None = None
        self._runner = CallableRunner(self)
        self._runner.finished.connect(self._on_finished)
        self._runner.failed.connect(self._on_failed)
        self._poller: VlmPoller | None = None
        self._pending = ""
        self._last_result: DetectionResult | None = None

        self._build()
        if self._detector is not None:
            self._apply_loaded(self._detector)
            self._status.setText("Previously loaded model is ready.")
        elif self._staged_config is not None:
            model = self._staged_config.model.strip()
            if model:
                self._model_combo.addItem(_model_text(OllamaModel(model)), userData=model)
            self._status.setText(
                "Saved settings restored. Press Check service, then Load model."
            )

    # -- construction --------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        note = QLabel(
            "This is advisory analysis only. The model's answer is never used to fly "
            "the aircraft and is never shown as a calibrated confidence."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #5b6470;")
        layout.addWidget(note)

        form = QFormLayout()

        self._base_url = QLineEdit(self._initial_config().base_url)
        form.addRow("Ollama base URL", self._base_url)

        model_row = QWidget()
        model_layout = QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        self._model_combo = QComboBox()
        self._check_button = QPushButton("Check service")
        self._check_button.clicked.connect(self.check_service)
        model_layout.addWidget(self._model_combo, 1)
        model_layout.addWidget(self._check_button)
        form.addRow("Model", model_row)

        self._target = QLineEdit(self._initial_config().target)
        form.addRow("Target object", self._target)

        self._interval = QDoubleSpinBox()
        self._interval.setRange(0.2, 30.0)
        self._interval.setSingleStep(0.5)
        self._interval.setDecimals(1)
        self._interval.setSuffix(" s")
        self._interval.setValue(self._initial_config().interval_s)
        form.addRow("Analysis interval", self._interval)

        self._timeout = QDoubleSpinBox()
        self._timeout.setRange(5.0, 600.0)
        self._timeout.setSingleStep(5.0)
        self._timeout.setDecimals(0)
        self._timeout.setSuffix(" s")
        self._timeout.setValue(self._initial_config().timeout_s)
        form.addRow("Request timeout", self._timeout)

        layout.addLayout(form)

        prompt_label = QLabel("Prompt template — $target is replaced with the target object")
        prompt_label.setStyleSheet("color: #5b6470;")
        layout.addWidget(prompt_label)
        self._prompt = QPlainTextEdit(self._initial_config().prompt_template)
        self._prompt.setMinimumHeight(150)
        layout.addWidget(self._prompt, 1)

        # Editing the target rewrites the JSON example's label to $target, so
        # every rendered prompt names the same object the operator asked for.
        self._target.textChanged.connect(self._sync_label_with_target)

        buttons = QHBoxLayout()
        self._load_button = QPushButton("Load model")
        self._load_button.setEnabled(False)
        self._load_button.clicked.connect(self.load_model)
        self._analyze_button = QPushButton("Analyze current frame")
        self._analyze_button.setEnabled(False)
        self._analyze_button.clicked.connect(self.analyze_once)
        self._periodic_button = QPushButton("Start periodic analysis")
        self._periodic_button.setEnabled(False)
        self._periodic_button.setCheckable(True)
        self._periodic_button.toggled.connect(self._on_periodic_toggled)
        buttons.addWidget(self._load_button)
        buttons.addWidget(self._analyze_button)
        buttons.addWidget(self._periodic_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._status = QLabel("Not checked")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #5b6470;")
        layout.addWidget(self._status)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def _initial_config(self) -> VlmConfig:
        if self._detector is not None:
            return self._detector.config
        if self._staged_config is not None:
            return self._staged_config
        return VlmConfig()

    # -- configuration -------------------------------------------------------

    def current_config(self) -> VlmConfig:
        return VlmConfig(
            base_url=self._base_url.text().strip() or VlmConfig().base_url,
            model=self._selected_model(),
            target=self._target.text().strip() or "target object",
            prompt_template=self._prompt.toPlainText() or DEFAULT_PROMPT,
            interval_s=self._interval.value(),
            timeout_s=self._timeout.value(),
        )

    def _selected_model(self) -> str:
        data = self._model_combo.currentData()
        if isinstance(data, str) and data:
            return data
        return self._model_combo.currentText()

    def _sync_label_with_target(self, _text: str) -> None:
        prompt = self._prompt.toPlainText()
        updated = _LABEL_FIELD.sub(r'\1"$target"', prompt, count=1)
        if updated != prompt:
            self._prompt.setPlainText(updated)

    # -- service discovery ---------------------------------------------------

    def check_service(self) -> bool:
        base_url = self._base_url.text().strip()
        self._status.setText("Checking Ollama…")
        self._pending = "probe"
        return self._runner.submit(lambda: self._probe(base_url))

    def _probe(self, base_url: str) -> tuple[OllamaClient, tuple[OllamaModel, ...]]:
        """Runs on the worker thread; resolves image support for every model."""
        client = self._client_factory(base_url)
        models = client.list_models()
        described: list[OllamaModel] = []
        for model in models:
            try:
                described.append(client.model_info(model.name))
            except Exception:  # noqa: BLE001 - a single bad entry must not hide the rest
                described.append(model)
        return client, tuple(described)

    def _on_probe_finished(
        self, client: OllamaClient, models: tuple[OllamaModel, ...]
    ) -> None:
        self._client = client
        previous = self._selected_model()
        if not previous and self._detector is not None:
            previous = self._detector.config.model
        self._model_combo.clear()
        for model in models:
            self._model_combo.addItem(_model_text(model), userData=model.name)
        index = self._model_combo.findData(previous)
        self._model_combo.setCurrentIndex(max(index, 0))
        if not models:
            self._load_button.setEnabled(False)
            self._status.setText(
                "Ollama answered, but no models are installed. Run `ollama pull llava` first."
            )
            return
        self._load_button.setEnabled(True)
        self._status.setText(f"Found {len(models)} installed model(s). Pick one and load it.")

    # -- model lifecycle -----------------------------------------------------

    def load_model(self) -> bool:
        try:
            config = self.current_config()
        except ValueError as exc:
            widgets.show_error(self, "VLM", str(exc))
            return False
        if not config.model:
            widgets.show_error(self, "VLM", "Choose an installed model first.")
            return False
        client = self._client or self._client_factory(config.base_url)
        self._status.setText(
            "Loading VLM model into memory… the first load can take a few minutes."
        )
        self._pending = "load"
        return self._runner.submit(lambda: self._load_candidate(config, client))

    def _load_candidate(self, config: VlmConfig, client: OllamaClient) -> OllamaVlmDetector:
        detector = self._detector_factory(config, client=client)
        detector.load()
        return detector

    def _on_loaded(self, detector: OllamaVlmDetector) -> None:
        self._detector = detector
        self._apply_loaded(detector)
        self._status.setText(
            f"Ready: {detector.name}. Image support verified by Ollama."
        )

    def _apply_loaded(self, detector: OllamaVlmDetector) -> None:
        config = detector.config
        self._target.setText(config.target)
        self._interval.setValue(config.interval_s)
        self._timeout.setValue(config.timeout_s)
        self._prompt.setPlainText(config.prompt_template)
        self._show_loaded_model(detector)
        self._analyze_button.setEnabled(True)
        self._periodic_button.setEnabled(True)

    def _show_loaded_model(self, detector: OllamaVlmDetector) -> None:
        """Show the active model in the dropdown, not an empty box.

        Reopening the dialog with a model already loaded used to leave the
        ComboBox blank, which reads as "nothing is configured" even though
        analysis is running with a model.
        """
        model = detector.config.model
        if not model:
            return
        # The detector only becomes ready after Ollama confirmed image support.
        known = detector.models or (OllamaModel(model, capabilities=("vision",)),)
        if self._model_combo.count() == 0:
            for entry in known:
                self._model_combo.addItem(_model_text(entry), userData=entry.name)
        index = self._model_combo.findData(model)
        if index < 0:
            self._model_combo.addItem(model, userData=model)
            index = self._model_combo.count() - 1
        self._model_combo.setCurrentIndex(index)
        self._load_button.setEnabled(True)

    # -- analysis ------------------------------------------------------------

    def analyze_once(self) -> bool:
        detector = self._detector
        frame = self._frame_provider()
        if detector is None or frame is None:
            self._status.setText("Load a model and wait for a frame first.")
            return False
        self._pending = "analyze"
        self._status.setText("Analyzing…")
        return self._runner.submit(lambda: detector.detect(frame))

    def _on_periodic_toggled(self, checked: bool) -> None:
        if checked:
            self.start_periodic()
        else:
            self.stop_periodic()
            self._periodic_button.setText("Start periodic analysis")

    def start_periodic(self) -> bool:
        detector = self._detector
        if detector is None:
            return False
        if self._poller is None:
            self._poller = VlmPoller(
                detector,
                self._frame_provider,
                interval_s=self._interval.value(),
                parent=self,
            )
            self._poller.result_ready.connect(self.show_result)
            self._poller.failed.connect(self._on_poller_failed)
        self._poller.set_interval(self._interval.value())
        self._poller.start()
        self._set_periodic_checked(True)
        self._periodic_button.setText("Stop periodic analysis")
        self._status.setText(
            f"Analyzing every {self._interval.value():.1f} s. "
            "A slow answer is never queued behind another."
        )
        return True

    def stop_periodic(self) -> None:
        if self._poller is not None:
            self._poller.stop()
        self._set_periodic_checked(False)
        self._periodic_button.setText("Start periodic analysis")

    def _set_periodic_checked(self, checked: bool) -> None:
        self._periodic_button.blockSignals(True)
        self._periodic_button.setChecked(checked)
        self._periodic_button.blockSignals(False)

    def show_result(self, result: object) -> None:
        if not isinstance(result, DetectionResult):
            return
        self._last_result = result
        self._status.setText(self.format_result(result))
        self._status.setStyleSheet(
            "color: #b26a00;" if self.is_stale(result) else "color: #2f6f44;"
        )

    def format_result(self, result: DetectionResult) -> str:
        latency = f"{result.latency_ms:.0f} ms" if result.latency_ms is not None else "n/a"
        frame_age = max(0.0, time.monotonic() - result.frame_timestamp)
        result_age = max(0.0, time.monotonic() - result.processed_at)
        prefix = (
            f"{result.detector_name} | latency {latency} | "
            f"frame {frame_age:.1f} s old | result {result_age:.1f} s old"
        )
        stale = " | STALE" if self.is_stale(result) else ""
        if result.failed:
            return f"{prefix} | error: {result.error}{stale}"
        if not result.detections:
            return f"{prefix} | target not visible{stale}"
        detection = result.detections[0]
        return f"{prefix} | {detection.label} (unscored){stale}"

    def is_stale(self, result: DetectionResult) -> bool:
        threshold = max(_STALE_FLOOR_S, 3.0 * self._interval.value())
        return (time.monotonic() - result.processed_at) > threshold

    # -- worker signals ------------------------------------------------------

    def _on_finished(self, result: object) -> None:
        if self._pending == "probe" and isinstance(result, tuple) and len(result) == 2:
            client, models = result
            self._on_probe_finished(client, models)
        elif self._pending == "load" and isinstance(result, OllamaVlmDetector):
            self._on_loaded(result)
        elif self._pending == "analyze" and isinstance(result, DetectionResult):
            self.show_result(result)

    def _on_failed(self, message: str) -> None:
        self._status.setText(f"Failed: {message}")
        self._status.setStyleSheet("color: #a12a2a;")
        if self._pending in ("probe", "load"):
            widgets.show_error(self, "VLM", message)

    def _on_poller_failed(self, message: str) -> None:
        self._status.setText(f"Periodic analysis failed: {message}")
        self._status.setStyleSheet("color: #a12a2a;")

    # -- save ----------------------------------------------------------------

    def save(self) -> None:
        detector = self._detector
        if detector is None:
            widgets.show_error(self, "VLM", "Load a model successfully before saving.")
            return
        config = self.current_config()
        detector.update_config(config)
        if self._poller is not None:
            self._poller.set_interval(config.interval_s)
        self._services.detectors[DetectorKind.VLM] = detector
        self._services.detector_events.publish(DetectorKind.VLM)
        try:
            self._store_profile(config)
        except Exception as exc:  # noqa: BLE001 - reported, the dialog stays open
            widgets.show_error(self, "VLM", exc)
            return
        self.stop_periodic()
        _log.info(
            "VLM settings saved",
            extra={"context": {"model": config.model, "interval_s": config.interval_s}},
        )
        self.accept()

    def _store_profile(self, config: VlmConfig) -> None:
        store_profile_section(self._services, "vlm", config.to_dict())

    # -- teardown ------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self.stop_periodic()
        super().closeEvent(event)

    # -- accessors used by tests --------------------------------------------

    @property
    def detector(self) -> OllamaVlmDetector | None:
        return self._detector

    @property
    def model_combo(self) -> QComboBox:
        return self._model_combo

    @property
    def status_label(self) -> QLabel:
        return self._status

    @property
    def analyze_button(self) -> QPushButton:
        return self._analyze_button

    @property
    def interval_spin(self) -> QDoubleSpinBox:
        return self._interval

    @property
    def target_edit(self) -> QLineEdit:
        return self._target

    @property
    def prompt_edit(self) -> QPlainTextEdit:
        return self._prompt

    @property
    def last_result(self) -> DetectionResult | None:
        return self._last_result

    @property
    def polling(self) -> bool:
        return self._poller is not None and self._poller.running


def _model_text(model: OllamaModel) -> str:
    support = model.supports_images
    if support is True:
        suffix = "vision"
    elif support is False:
        suffix = "no image support"
    else:
        suffix = "image support unknown"
    return f"{model.name} — {suffix}"
