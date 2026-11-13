"""VLM settings dialog: discovery, loading, periodic analysis and staleness."""

from __future__ import annotations

import json
import time

import numpy as np

from drone_vision_lab.adapters.vlm import OllamaClient
from drone_vision_lab.domain import DetectionResult, DetectorKind, Frame
from drone_vision_lab.ui.vlm_settings_dialog import VlmSettingsDialog

GOOD_ANSWER = json.dumps(
    {"visible": True, "label": "ball", "bbox": {"x": 0.3, "y": 0.3, "w": 0.2, "h": 0.2}}
)


class FakeTransport:
    def __init__(self, models, capabilities, answer=GOOD_ANSWER):
        self.models = [{"name": name} for name in models]
        self.capabilities = capabilities
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method, url, body, timeout):
        payload = json.loads(body) if body else {}
        self.calls.append((method, url))
        if url.endswith("/api/tags"):
            return 200, json.dumps({"models": self.models}).encode()
        if url.endswith("/api/show"):
            model = payload.get("model", "")
            capabilities = self.capabilities.get(model, [])
            return 200, json.dumps(
                {"capabilities": capabilities, "details": {"families": []}}
            ).encode()
        if url.endswith("/api/chat"):
            return 200, json.dumps({"message": {"content": self.answer}}).encode()
        return 404, b"unexpected"


def _frame() -> Frame:
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    return Frame(image=image, captured_at=time.monotonic(), source_id="test", index=0)


def _wait(qapp, predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _dialog(services, transport) -> VlmSettingsDialog:
    def factory(base_url: str) -> OllamaClient:
        return OllamaClient(base_url, transport=transport)

    return VlmSettingsDialog(
        services,
        _frame(),
        client_factory=factory,
        frame_provider=_frame,
    )


def _ready_dialog(qapp, services, transport) -> VlmSettingsDialog:
    dialog = _dialog(services, transport)
    assert dialog.check_service() is True
    assert _wait(qapp, lambda: dialog.model_combo.count() > 0)
    assert dialog.load_model() is True
    assert _wait(qapp, lambda: dialog.detector is not None)
    return dialog


def test_service_check_lists_models_and_marks_image_support(qapp, services):
    transport = FakeTransport(
        ["llava:7b", "llama3:8b"],
        {"llava:7b": ["completion", "vision"], "llama3:8b": ["completion"]},
    )
    dialog = _dialog(services, transport)

    dialog.check_service()
    assert _wait(qapp, lambda: dialog.model_combo.count() == 2)

    texts = [dialog.model_combo.itemText(i) for i in range(dialog.model_combo.count())]
    assert any("llava:7b" in text and "vision" in text for text in texts)
    assert any("llama3:8b" in text and "no image support" in text for text in texts)


def test_no_installed_models_is_reported(qapp, services):
    dialog = _dialog(services, FakeTransport([], {}))

    dialog.check_service()
    assert _wait(qapp, lambda: "no models are installed" in dialog.status_label.text())


def test_loading_verifies_image_support_and_stages_the_model(qapp, services):
    transport = FakeTransport(["llava:7b"], {"llava:7b": ["completion", "vision"]})
    dialog = _ready_dialog(qapp, services, transport)

    assert dialog.detector is not None
    assert dialog.detector.ready is True
    assert dialog.analyze_button.isEnabled()
    # Staged, not installed until Save.
    assert services.detectors[DetectorKind.VLM].ready is False


def test_an_unsupported_model_fails_with_a_clear_error(qapp, services, monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(
        "drone_vision_lab.ui.vlm_settings_dialog.widgets.show_error",
        lambda _parent, _title, error: shown.append(str(error)),
    )
    transport = FakeTransport(["llama3:8b"], {"llama3:8b": ["completion"]})
    dialog = _dialog(services, transport)
    dialog.check_service()
    assert _wait(qapp, lambda: dialog.model_combo.count() == 1)

    dialog.load_model()
    assert _wait(qapp, lambda: "Failed" in dialog.status_label.text())

    assert dialog.detector is None
    assert shown


def test_analyzing_once_reports_model_latency_and_frame_age(qapp, services):
    transport = FakeTransport(["llava:7b"], {"llava:7b": ["vision"]})
    dialog = _ready_dialog(qapp, services, transport)

    assert dialog.analyze_once() is True
    assert _wait(qapp, lambda: dialog.last_result is not None)

    status = dialog.status_label.text()
    assert "llava:7b" in status
    assert "latency" in status
    assert "frame" in status and "old" in status
    assert "ball" in status


def test_a_slow_old_result_is_marked_stale(qapp, services):
    dialog = _dialog(services, FakeTransport([], {}))
    stale = DetectionResult(
        detector_name="Ollama VLM",
        kind=DetectorKind.VLM,
        processed_at=time.monotonic() - 30.0,
        frame_timestamp=time.monotonic() - 30.5,
    )

    dialog.show_result(stale)

    assert dialog.is_stale(stale) is True
    assert "STALE" in dialog.status_label.text()


def test_errors_are_shown_as_errors_not_as_not_visible(qapp, services):
    dialog = _dialog(services, FakeTransport([], {}))
    failed = DetectionResult(
        detector_name="Ollama VLM",
        kind=DetectorKind.VLM,
        processed_at=time.monotonic(),
        frame_timestamp=time.monotonic(),
        error="VLM answer rejected: the answer was not valid JSON",
    )

    text = dialog.format_result(failed)

    assert "error:" in text
    assert "not visible" not in text


def test_periodic_analysis_can_be_started_and_stopped(qapp, services):
    transport = FakeTransport(["llava:7b"], {"llava:7b": ["vision"]})
    dialog = _ready_dialog(qapp, services, transport)

    assert dialog.start_periodic() is True
    assert dialog.polling is True
    dialog.stop_periodic()
    assert dialog.polling is False


def test_saving_installs_the_detector_and_persists_config(qapp, services):
    transport = FakeTransport(["llava:7b"], {"llava:7b": ["vision"]})
    dialog = _ready_dialog(qapp, services, transport)

    dialog.save()

    assert services.detectors[DetectorKind.VLM] is dialog.detector
    profile = services.profiles.get("default")
    assert profile is not None
    payload = profile.payload["vlm"]
    assert payload["schema_version"] == 1
    assert payload["model"] == "llava:7b"
    assert payload["interval_s"] == 1.0


def test_saved_settings_are_shown_before_the_model_is_loaded(qapp, services):
    from drone_vision_lab.adapters.vlm import OllamaVlmDetector, VlmConfig

    services.detectors[DetectorKind.VLM] = OllamaVlmDetector(
        VlmConfig(model="llava:7b", target="red apple", interval_s=2.0)
    )

    dialog = _dialog(services, FakeTransport([], {}))

    assert dialog.detector is None
    assert dialog.model_combo.currentData() == "llava:7b"
    assert dialog.target_edit.text() == "red apple"
    assert dialog.interval_spin.value() == 2.0
    assert "Saved settings restored" in dialog.status_label.text()


def test_changing_the_target_updates_the_prompt_label(qapp, services):
    dialog = _dialog(services, FakeTransport([], {}))
    dialog.prompt_edit.setPlainText(
        '{"visible": true, "label": "apple", "bbox": '
        '{"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}}'
    )

    dialog.target_edit.setText("red apple")

    text = dialog.prompt_edit.toPlainText()
    assert '"label": "$target"' in text
    assert '"apple"' not in text
    # Further edits leave the rest of the template alone.
    dialog.target_edit.setText("green ball")
    assert dialog.prompt_edit.toPlainText() == text


def test_reopening_the_dialog_shows_the_loaded_model(qapp, services):
    transport = FakeTransport(["llava:7b"], {"llava:7b": ["completion", "vision"]})
    first = _ready_dialog(qapp, services, transport)
    first.save()

    reopened = _dialog(services, transport)

    assert reopened.detector is not None
    assert reopened.model_combo.count() == 1
    assert "llava:7b" in reopened.model_combo.currentText()
    # Saving again with no probe must keep the same model.
    reopened.save()
    profile = services.profiles.get("default")
    assert profile is not None
    assert profile.payload["vlm"]["model"] == "llava:7b"


def test_vlm_never_offers_a_confidence(qapp, services):
    transport = FakeTransport(["llava:7b"], {"llava:7b": ["vision"]})
    dialog = _ready_dialog(qapp, services, transport)
    dialog.analyze_once()
    assert _wait(qapp, lambda: dialog.last_result is not None)

    assert dialog.last_result is not None
    assert all(d.confidence is None for d in dialog.last_result.detections)
    assert "unscored" in dialog.status_label.text()


def test_the_workspace_tab_reports_vlm_configuration(qapp, services):
    from drone_vision_lab.ui.tabs.vision_lab import VisionLabTab

    tab = VisionLabTab(services)
    assert "not configured" in tab.vlm_label.text()
