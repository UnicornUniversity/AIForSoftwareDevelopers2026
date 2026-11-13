"""YOLO settings dialog: worker-thread loading, class metadata and saving."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from drone_vision_lab.adapters.vision import YoloDetector
from drone_vision_lab.domain import DetectorKind, Frame
from drone_vision_lab.ui.yolo_settings_dialog import YoloSettingsDialog

NAMES = {0: "person", 32: "sports ball", 47: "apple"}


class _Boxes:
    def __init__(self, xyxy, conf, cls):
        self.xyxy = np.asarray(xyxy, dtype=np.float32).reshape(-1, 4)
        self.conf = np.asarray(conf, dtype=np.float32)
        self.cls = np.asarray(cls, dtype=np.float32)


class _Model:
    def __init__(self, boxes=None):
        self.names = dict(NAMES)
        self.boxes = boxes
        self.calls: list[dict[str, object]] = []

    def predict(self, image, **kwargs):
        self.calls.append(kwargs)
        return [SimpleNamespace(boxes=self.boxes)]


def _frame() -> Frame:
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    return Frame(image=image, captured_at=time.monotonic(), source_id="test", index=0)


def _weights(tmp_path: Path) -> Path:
    path = tmp_path / "yolo11n.pt"
    path.write_bytes(b"placeholder")
    return path


def _wait(qapp, predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _dialog(services, tmp_path: Path, model: _Model | None = None) -> YoloSettingsDialog:
    model = model or _Model()
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))

    def factory(config):
        return YoloDetector(
            config,
            ultralytics_module=SimpleNamespace(YOLO=lambda _path: model),
            torch_module=torch,
        )

    dialog = YoloSettingsDialog(services, _frame(), detector_factory=factory)
    dialog.model_path_edit.setText(str(_weights(tmp_path)))
    return dialog


def test_loading_populates_classes_from_model_metadata(qapp, services, tmp_path):
    dialog = _dialog(services, tmp_path)

    assert dialog.load_model() is True
    assert _wait(qapp, lambda: dialog.detector is not None)

    classes = [dialog.class_combo.itemText(i) for i in range(dialog.class_combo.count())]
    assert classes == ["apple", "person", "sports ball"]
    assert dialog.class_combo.currentText() == "apple"
    assert dialog.test_button.isEnabled()
    assert "cpu" in dialog.device_label.text()


def test_weights_are_discovered_in_the_app_directory(qapp, services, tmp_path, monkeypatch):
    import drone_vision_lab.ui.yolo_settings_dialog as module

    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "yolo11m.pt").write_bytes(b"placeholder")
    (tmp_path / "custom.pt").write_bytes(b"placeholder")
    monkeypatch.setattr(module, "_APP_ROOT", tmp_path)

    dialog = YoloSettingsDialog(services, _frame())

    assert dialog.model_path_edit.text() == str(tmp_path / "models" / "yolo11m.pt")


def test_the_default_path_is_the_app_directory_when_no_weights_exist(
    qapp, services, tmp_path, monkeypatch
):
    import drone_vision_lab.ui.yolo_settings_dialog as module

    monkeypatch.setattr(module, "_APP_ROOT", tmp_path)

    dialog = YoloSettingsDialog(services, _frame())

    assert dialog.model_path_edit.text() == str(tmp_path / "yolo11n.pt")


def test_a_loaded_model_is_staged_until_saved(qapp, services, tmp_path):
    dialog = _dialog(services, tmp_path)
    assert dialog.load_model() is True
    assert _wait(qapp, lambda: dialog.detector is not None)

    assert services.detectors[DetectorKind.YOLO].ready is False

    dialog.class_combo.setCurrentText("apple")
    dialog.save()

    installed = services.detectors[DetectorKind.YOLO]
    assert installed is dialog.detector
    assert installed.ready is True
    assert installed.config.class_label == "apple"


def test_save_stores_a_versioned_profile(qapp, services, tmp_path):
    dialog = _dialog(services, tmp_path)
    dialog.load_model()
    assert _wait(qapp, lambda: dialog.detector is not None)

    dialog.save()

    profile = services.profiles.get("default")
    assert profile is not None
    assert profile.payload["yolo"]["schema_version"] == 1
    assert profile.payload["yolo"]["class_label"] == "apple"


def test_test_run_reports_count_latency_and_confidence(qapp, services, tmp_path):
    model = _Model(boxes=_Boxes([[80, 60, 160, 140]], [0.88], [32]))
    dialog = _dialog(services, tmp_path, model)
    dialog.load_model()
    assert _wait(qapp, lambda: dialog.detector is not None)

    assert dialog.test_on_frame() is True
    assert _wait(qapp, lambda: "Running inference" not in dialog.status_label.text())

    status = dialog.status_label.text()
    assert "1 detection(s)" in status
    assert "confidence 0.88" in status
    assert model.calls[-1]["classes"] == [47]


def test_test_run_reports_no_target_separately_from_failure(qapp, services, tmp_path):
    dialog = _dialog(services, tmp_path, _Model(boxes=_Boxes([], [], [])))
    dialog.load_model()
    assert _wait(qapp, lambda: dialog.detector is not None)

    dialog.test_on_frame()
    assert _wait(qapp, lambda: "Running inference" not in dialog.status_label.text())

    assert "No target found" in dialog.status_label.text()


def test_a_missing_weights_file_is_reported(qapp, services, tmp_path, monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(
        "drone_vision_lab.ui.yolo_settings_dialog.widgets.show_error",
        lambda _parent, _title, _error: shown.append(str(_error)),
    )
    dialog = YoloSettingsDialog(services, _frame())
    dialog.model_path_edit.setText(str(tmp_path / "absent.pt"))

    assert dialog.load_model() is True
    assert _wait(qapp, lambda: "could not be loaded" in dialog.status_label.text())

    assert shown


def test_saving_without_a_loaded_model_is_refused(services, qapp, monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(
        "drone_vision_lab.ui.yolo_settings_dialog.widgets.show_error",
        lambda _parent, _title, _error: shown.append(str(_error)),
    )
    dialog = YoloSettingsDialog(services, _frame())

    dialog.save()

    assert shown
    assert services.detectors[DetectorKind.YOLO].ready is False


def test_the_workspace_tab_reports_yolo_configuration(qapp, services, tmp_path):
    from drone_vision_lab.ui.tabs.vision_lab import VisionLabTab

    tab = VisionLabTab(services)
    assert "not configured" in tab.yolo_label.text()

    dialog = _dialog(services, tmp_path)
    dialog.load_model()
    assert _wait(qapp, lambda: dialog.detector is not None)
    dialog.save()

    tab.refresh_yolo_status()
    assert "apple" in tab.yolo_label.text()


# -- detector change broadcasts ----------------------------------------------


def test_saving_announces_the_new_detector(qapp, services, tmp_path):
    seen: list[DetectorKind] = []
    services.detector_events.subscribe(seen.append)
    dialog = _dialog(services, tmp_path)
    dialog.load_model()
    assert _wait(qapp, lambda: dialog.detector is not None)

    dialog.save()

    assert seen == [DetectorKind.YOLO]


def test_a_save_without_a_loaded_model_announces_nothing(qapp, services, monkeypatch):
    monkeypatch.setattr(
        "drone_vision_lab.ui.yolo_settings_dialog.widgets.show_error",
        lambda *_args: None,
    )
    seen: list[DetectorKind] = []
    services.detector_events.subscribe(seen.append)
    dialog = YoloSettingsDialog(services, _frame())

    dialog.save()

    assert seen == []


def test_saving_yolo_elsewhere_refreshes_the_apple_preset_gate(
    window, services, qapp, tmp_path
):
    """A save from another tab must reach the preset tab's Execute gate.

    A profile is already active, so storing the settings emits no state change:
    only the detector-change signal can refresh the tab. Without it the button
    stayed disabled next to a loaded model.
    """
    services.drone_mode = "tello"
    services.state.update(active_profile_id="default")
    window.drone_tab.connect_button.click()
    tab = window.preset_missions_tab
    tab.program_combo.setCurrentIndex(2)
    assert tab.execute_button.isEnabled() is False
    assert "YOLO" in tab.execute_button.toolTip()

    dialog = _dialog(services, tmp_path)
    dialog.load_model()
    assert _wait(qapp, lambda: dialog.detector is not None)
    dialog.save()

    assert tab.execute_button.isEnabled() is True
    assert "YOLO" in tab.target_label.text()
