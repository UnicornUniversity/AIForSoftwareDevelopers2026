"""YOLO detector: model-metadata classes, box parsing and device fallback.

The Ultralytics runtime is replaced with a double, so these tests run without
the ``yolo`` extra, without weights and without a GPU. The single test that
needs a real model is marked ``model`` and skips unless a weights file is
provided.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from drone_vision_lab.adapters.vision.yolo_detector import (
    YoloDetector,
    YoloDetectorConfig,
    parse_yolo_boxes,
)
from drone_vision_lab.domain import Frame
from drone_vision_lab.errors import ConfigurationError, VisionError

COCO_NAMES = {0: "person", 32: "sports ball", 47: "apple", 49: "orange"}


class _Boxes:
    def __init__(self, xyxy, conf, cls):
        self.xyxy = np.asarray(xyxy, dtype=np.float32).reshape(-1, 4)
        self.conf = np.asarray(conf, dtype=np.float32)
        self.cls = np.asarray(cls, dtype=np.float32)


class _Model:
    def __init__(self, names, boxes=None, error=None):
        self.names = dict(names)
        self.boxes = boxes
        self.error = error
        self.calls: list[dict[str, object]] = []

    def predict(self, image, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise RuntimeError(self.error)
        return [SimpleNamespace(boxes=self.boxes)]


def _frame(width: int = 320, height: int = 240) -> Frame:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    return Frame(image=image, captured_at=time.monotonic(), source_id="test", index=0)


def _torch(available: bool):
    return SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: available))


def _weights(tmp_path: Path) -> Path:
    path = tmp_path / "yolo11n.pt"
    path.write_bytes(b"not a real checkpoint")
    return path


def _detector(
    tmp_path: Path,
    *,
    boxes=None,
    model_error: str | None = None,
    cuda: bool = False,
    config: YoloDetectorConfig | None = None,
) -> tuple[YoloDetector, _Model]:
    model = _Model(COCO_NAMES, boxes=boxes, error=model_error)
    config = config or YoloDetectorConfig(model_path=str(_weights(tmp_path)))
    detector = YoloDetector(
        config,
        ultralytics_module=SimpleNamespace(YOLO=lambda _path: model),
        torch_module=_torch(cuda),
    )
    detector.load()
    return detector, model


# -- box parsing -------------------------------------------------------------


def test_parses_pixel_boxes_into_normalized_boxes():
    boxes = _Boxes([[80, 60, 160, 140]], [0.91], [32])

    detections = parse_yolo_boxes(boxes, COCO_NAMES, (320, 240), max_detections=5)

    assert len(detections) == 1
    detection = detections[0]
    assert detection.label == "sports ball"
    assert detection.confidence == pytest.approx(0.91, abs=1e-5)
    assert detection.box.x == pytest.approx(0.25)
    assert detection.box.y == pytest.approx(0.25)
    assert detection.box.w == pytest.approx(0.25)
    assert detection.box.h == pytest.approx(1.0 / 3.0, abs=1e-5)


def test_pixel_boxes_are_exactly_derivable():
    boxes = _Boxes([[80, 60, 160, 140]], [0.9], [32])
    detection = parse_yolo_boxes(boxes, COCO_NAMES, (320, 240), max_detections=5)[0]

    pixel_box = detection.box.to_pixels((320, 240))
    assert (pixel_box.x, pixel_box.y, pixel_box.w, pixel_box.h) == pytest.approx(
        (80.0, 60.0, 80.0, 80.0), abs=1.0
    )


def test_boxes_are_clamped_to_the_frame():
    boxes = _Boxes([[-20, -10, 400, 300]], [0.5], [0])

    detection = parse_yolo_boxes(boxes, COCO_NAMES, (320, 240), max_detections=5)[0]

    assert detection.box.x == 0.0
    assert detection.box.y == 0.0
    assert detection.box.x + detection.box.w == pytest.approx(1.0)
    assert detection.box.y + detection.box.h == pytest.approx(1.0)


def test_degenerate_boxes_are_dropped():
    boxes = _Boxes([[10, 10, 10.5, 10.5], [40, 40, 100, 100]], [0.8, 0.7], [0, 0])

    detections = parse_yolo_boxes(boxes, COCO_NAMES, (320, 240), max_detections=5)

    assert len(detections) == 1
    assert detections[0].box.x == pytest.approx(40 / 320)


def test_max_detections_is_respected():
    boxes = _Boxes(
        [[10, 10, 50, 50], [60, 60, 100, 100], [120, 120, 160, 160]],
        [0.9, 0.8, 0.7],
        [0, 0, 0],
    )
    assert len(parse_yolo_boxes(boxes, COCO_NAMES, (320, 240), max_detections=2)) == 2


def test_unknown_class_id_falls_back_to_the_id_as_a_string():
    boxes = _Boxes([[10, 10, 50, 50]], [0.9], [999])
    assert parse_yolo_boxes(boxes, COCO_NAMES, (320, 240), max_detections=5)[0].label == "999"


def test_missing_boxes_yield_no_detections():
    assert parse_yolo_boxes(None, COCO_NAMES, (320, 240), max_detections=5) == ()


# -- model loading -----------------------------------------------------------


def test_class_names_come_from_the_model_not_from_the_code(tmp_path):
    detector, _ = _detector(tmp_path)

    assert detector.available_classes == tuple(sorted(COCO_NAMES.items()))
    assert detector.class_id_for_label("apple") == 47
    assert detector.class_id_for_label("banana") is None


def test_auto_device_falls_back_to_cpu_without_cuda(tmp_path):
    detector, _ = _detector(tmp_path, cuda=False)

    assert detector.device == "cpu"
    assert "CPU" in detector.device_note


def test_auto_device_uses_cuda_when_available(tmp_path):
    detector, _ = _detector(tmp_path, cuda=True)

    assert detector.device == "cuda:0"


def test_requested_cuda_without_cuda_falls_back_and_says_so(tmp_path):
    config = YoloDetectorConfig(model_path=str(_weights(tmp_path)), device="cuda:0")
    detector, _ = _detector(tmp_path, cuda=False, config=config)

    assert detector.device == "cpu"
    assert "falling back" in detector.device_note.lower()


def test_a_broken_cuda_probe_is_reported_as_a_problem_not_as_no_gpu(tmp_path, caplog):
    """A raising probe means a broken install, not a machine without a GPU."""

    def boom() -> bool:
        raise RuntimeError("cuda driver version mismatch")

    torch_module = SimpleNamespace(cuda=SimpleNamespace(is_available=boom))
    detector = YoloDetector(
        YoloDetectorConfig(model_path=str(_weights(tmp_path))),
        ultralytics_module=SimpleNamespace(YOLO=lambda _path: _Model(COCO_NAMES)),
        torch_module=torch_module,
    )

    detector.load()

    assert detector.device == "cpu"
    assert "no cuda gpu" not in detector.device_note.lower()
    assert "probe failed" in detector.device_note.lower()
    assert "cuda driver version mismatch" in caplog.text


def test_missing_weights_file_is_refused(tmp_path):
    detector = YoloDetector(
        YoloDetectorConfig(model_path=str(tmp_path / "absent.pt")),
        ultralytics_module=SimpleNamespace(YOLO=lambda _path: _Model(COCO_NAMES)),
    )

    with pytest.raises(VisionError, match="not found"):
        detector.load()


def test_empty_model_path_is_refused():
    detector = YoloDetector(YoloDetectorConfig(model_path=""))

    with pytest.raises(VisionError, match="No YOLO model selected"):
        detector.load()


def test_missing_ultralytics_package_is_reported(monkeypatch, tmp_path):
    from drone_vision_lab.adapters.vision import yolo_detector

    def _boom():
        raise VisionError("Ultralytics is not installed", user_message="pip install it")

    monkeypatch.setattr(yolo_detector, "require_ultralytics", _boom)
    detector = YoloDetector(YoloDetectorConfig(model_path=str(_weights(tmp_path))))

    with pytest.raises(VisionError, match="Ultralytics is not installed"):
        detector.load()


def test_a_broken_checkpoint_is_reported_as_a_vision_error(tmp_path):
    def _raise(_path):
        raise RuntimeError("torch.load failed")

    detector = YoloDetector(
        YoloDetectorConfig(model_path=str(_weights(tmp_path))),
        ultralytics_module=SimpleNamespace(YOLO=_raise),
    )

    with pytest.raises(VisionError, match="could not load"):
        detector.load()


# -- inference ---------------------------------------------------------------


def test_detect_returns_detections_with_latency(tmp_path):
    detector, _ = _detector(tmp_path, boxes=_Boxes([[80, 60, 160, 140]], [0.92], [32]))

    result = detector.detect(_frame())

    assert result.failed is False
    assert result.found is True
    assert result.latency_ms is not None and result.latency_ms >= 0.0
    assert result.detections[0].label == "sports ball"


def test_detect_requests_only_the_selected_class(tmp_path):
    detector, model = _detector(tmp_path, boxes=_Boxes([], [], []))

    detector.detect(_frame())

    call = model.calls[0]
    # The default target class is apple, which this model maps to id 47.
    assert call["classes"] == [47]
    assert call["conf"] == pytest.approx(0.35)
    assert call["device"] == "cpu"


def test_a_class_the_model_does_not_know_is_an_error_and_skips_inference(tmp_path):
    config = YoloDetectorConfig(model_path=str(_weights(tmp_path)), class_label="tennis racket")
    detector, model = _detector(tmp_path, config=config)

    result = detector.detect(_frame())

    assert result.failed
    assert "not present in this model" in (result.error or "")
    assert model.calls == []


def test_unloaded_detector_reports_an_error(tmp_path):
    detector = YoloDetector(YoloDetectorConfig(model_path=str(_weights(tmp_path))))

    result = detector.detect(_frame())

    assert result.failed
    assert detector.ready is False


def test_inference_failure_becomes_an_error_result_not_an_exception(tmp_path):
    detector, _ = _detector(tmp_path, model_error="CUDA out of memory")

    result = detector.detect(_frame())

    assert result.failed
    assert "CUDA out of memory" in (result.error or "")


def test_detect_all_classes_does_not_filter_by_the_target_class(tmp_path):
    detector, model = _detector(
        tmp_path,
        boxes=_Boxes(
            [[10, 10, 60, 60], [80, 60, 160, 140]],
            [0.61, 0.92],
            [0, 32],
        ),
    )

    result = detector.detect_all_classes(_frame())

    call = model.calls[0]
    assert "classes" not in call
    assert call["conf"] == pytest.approx(0.35)
    assert [detection.label for detection in result.detections] == ["person", "sports ball"]
    assert [detection.confidence for detection in result.detections] == pytest.approx(
        [0.61, 0.92], abs=1e-5
    )


def test_detect_all_classes_uses_the_configured_conf_and_iou(tmp_path):
    config = YoloDetectorConfig(
        model_path=str(_weights(tmp_path)),
        confidence_threshold=0.55,
        iou_threshold=0.4,
    )
    detector, model = _detector(tmp_path, boxes=_Boxes([], [], []), config=config)

    detector.detect_all_classes(_frame())

    assert model.calls[0]["conf"] == pytest.approx(0.55)
    assert model.calls[0]["iou"] == pytest.approx(0.4)


def test_detect_all_classes_without_a_model_reports_an_error(tmp_path):
    detector = YoloDetector(YoloDetectorConfig(model_path=str(_weights(tmp_path))))

    result = detector.detect_all_classes(_frame())

    assert result.failed
    assert "not loaded" in (result.error or "")


def test_no_detections_is_not_a_failure(tmp_path):
    detector, _ = _detector(tmp_path, boxes=_Boxes([], [], []))

    result = detector.detect(_frame())

    assert result.failed is False
    assert result.found is False


# -- configuration -----------------------------------------------------------


def test_config_round_trip():
    config = YoloDetectorConfig(
        model_path="weights/yolo11n.pt",
        class_label="apple",
        confidence_threshold=0.6,
        device="cpu",
    )
    assert YoloDetectorConfig.from_dict(config.to_dict()) == config


def test_the_default_target_class_is_apple():
    assert YoloDetectorConfig().class_label == "apple"
    # Older saved configurations without the key fall back to the same default.
    assert YoloDetectorConfig.from_dict({"schema_version": 1}).class_label == "apple"


def test_config_rejects_an_unknown_schema_version():
    data = YoloDetectorConfig().to_dict()
    data["schema_version"] = 42
    with pytest.raises(ConfigurationError):
        YoloDetectorConfig.from_dict(data)


def test_config_rejects_out_of_range_thresholds():
    with pytest.raises(ValueError):
        YoloDetectorConfig(confidence_threshold=1.5)
    with pytest.raises(ValueError):
        YoloDetectorConfig(iou_threshold=-0.1)


# -- real model (opt-in) -----------------------------------------------------


@pytest.mark.model
def test_real_weights_file_loads(tmp_path):
    """Run with DRONE_VISION_LAB_YOLO_MODEL=<path to .pt> and the yolo extra."""
    model_path = os.environ.get("DRONE_VISION_LAB_YOLO_MODEL")
    if not model_path:
        pytest.skip("set DRONE_VISION_LAB_YOLO_MODEL to a local weights file")

    detector = YoloDetector(YoloDetectorConfig(model_path=model_path, class_label="sports ball"))
    detector.load()

    assert detector.ready
    assert detector.device
    assert detector.class_id_for_label("sports ball") is not None
