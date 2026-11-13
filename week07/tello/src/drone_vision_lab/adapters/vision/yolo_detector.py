"""Ultralytics YOLO detector.

Design points that matter for the classroom:

* Class names are read from the loaded model, never hard-coded. ``apple`` is
  the default target class, and alternatives such as ``sports ball`` are only
  offered when the model actually knows them.
* Weights are never downloaded silently. ``model_path`` must point at a file
  that already exists; a download is an explicit, confirmed operator action.
* GPU is optional. ``device="auto"`` picks CUDA when the installed PyTorch
  reports it, otherwise CPU, and the UI shows which one is active.
* Boxes are normalized to ``[0, 1]``; pixel boxes are exactly derivable with
  :meth:`BoundingBox.to_pixels` and are not stored twice.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np

from ...domain import BoundingBox, Detection, DetectionResult, DetectorKind, Frame
from ...errors import ConfigurationError, VisionError
from ..optional import require_ultralytics

__all__ = ["YoloDetector", "YoloDetectorConfig", "parse_yolo_boxes"]

_log = logging.getLogger(__name__)

CONFIG_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class YoloDetectorConfig:
    model_path: str = ""
    class_label: str = "apple"
    confidence_threshold: float = 0.35
    iou_threshold: float = 0.5
    max_detections: int = 10
    device: str = "auto"

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be within [0, 1]")
        if not 0.0 <= self.iou_threshold <= 1.0:
            raise ValueError("iou_threshold must be within [0, 1]")
        if self.max_detections < 1:
            raise ValueError("max_detections must be at least 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "model_path": self.model_path,
            "class_label": self.class_label,
            "confidence_threshold": self.confidence_threshold,
            "iou_threshold": self.iou_threshold,
            "max_detections": self.max_detections,
            "device": self.device,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> YoloDetectorConfig:
        if data.get("schema_version") != CONFIG_SCHEMA_VERSION:
            raise ConfigurationError(
                "Unsupported YOLO config schema version",
                user_message="This YOLO configuration was saved by an incompatible version.",
            )
        try:
            return cls(
                model_path=str(data.get("model_path", "")),
                class_label=str(data.get("class_label", "apple")),
                confidence_threshold=float(data.get("confidence_threshold", 0.35)),
                iou_threshold=float(data.get("iou_threshold", 0.5)),
                max_detections=int(data.get("max_detections", 10)),
                device=str(data.get("device", "auto")),
            )
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(
                f"Invalid YOLO configuration: {exc}",
                user_message="The saved YOLO configuration is invalid.",
            ) from exc


def _to_numpy(value: Any) -> np.ndarray:
    """Convert tensors or sequences from an Ultralytics result to NumPy."""
    if value is None:
        return np.empty((0,))
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def parse_yolo_boxes(
    boxes: Any,
    class_names: dict[int, str],
    frame_shape: tuple[int, int],
    *,
    max_detections: int,
) -> tuple[Detection, ...]:
    """Convert an Ultralytics ``Boxes`` object into detections.

    Accepts anything with ``xyxy``, ``conf`` and ``cls`` attributes, which is
    what both the real result object and the test doubles expose.
    """
    if boxes is None:
        return ()
    xyxy = _to_numpy(boxes.xyxy).reshape(-1, 4)
    confidence = _to_numpy(boxes.conf).reshape(-1)
    classes = _to_numpy(boxes.cls).reshape(-1)
    width, height = frame_shape

    detections: list[Detection] = []
    for index in range(min(len(xyxy), len(confidence), len(classes))):
        x1, y1, x2, y2 = (float(v) for v in xyxy[index])
        x1 = max(0.0, min(x1, float(width)))
        x2 = max(0.0, min(x2, float(width)))
        y1 = max(0.0, min(y1, float(height)))
        y2 = max(0.0, min(y2, float(height)))
        if x2 - x1 < 1.0 or y2 - y1 < 1.0:
            continue
        class_id = int(classes[index])
        left = min(1.0, x1 / width)
        top = min(1.0, y1 / height)
        detections.append(
            Detection(
                label=class_names.get(class_id, str(class_id)),
                box=BoundingBox(
                    x=left,
                    y=top,
                    w=min(1.0 - left, (x2 - x1) / width),
                    h=min(1.0 - top, (y2 - y1) / height),
                ),
                confidence=float(confidence[index]),
            )
        )
        if len(detections) >= max_detections:
            break
    return tuple(detections)


class YoloDetector:
    """COCO-pretrained (or custom) YOLO detector behind the detector contract."""

    def __init__(
        self,
        config: YoloDetectorConfig | None = None,
        *,
        ultralytics_module: ModuleType | None = None,
        torch_module: ModuleType | None = None,
    ) -> None:
        self._config = config or YoloDetectorConfig()
        self._ultralytics = ultralytics_module
        self._torch = torch_module
        self._model: Any | None = None
        self._class_names: dict[int, str] = {}
        self._device = "cpu"
        self._device_note = ""
        self._cuda_probe_failed = False

    # -- Detector contract ---------------------------------------------------

    @property
    def name(self) -> str:
        model = Path(self._config.model_path).name if self._config.model_path else "YOLO"
        return f"YOLO ({model})"

    @property
    def kind(self) -> DetectorKind:
        return DetectorKind.YOLO

    @property
    def ready(self) -> bool:
        return self._model is not None

    @property
    def config(self) -> YoloDetectorConfig:
        return self._config

    @property
    def class_names(self) -> dict[int, str]:
        return dict(self._class_names)

    @property
    def available_classes(self) -> tuple[tuple[int, str], ...]:
        return tuple(sorted(self._class_names.items()))

    @property
    def device(self) -> str:
        return self._device

    @property
    def device_note(self) -> str:
        return self._device_note

    def update_config(self, config: YoloDetectorConfig) -> None:
        self._config = config

    def load(self) -> None:
        path_text = self._config.model_path.strip()
        if not path_text:
            raise VisionError(
                "No YOLO model selected",
                user_message=(
                    "Choose a local YOLO weights file first. The application never "
                    "downloads weights without an explicit action."
                ),
            )
        path = Path(path_text)
        if not path.is_file():
            raise VisionError(
                f"YOLO weights not found: {path}",
                user_message=(
                    f"The weights file was not found:\n{path}\n\n"
                    "Download or copy the .pt file yourself, then select it again."
                ),
            )
        ultralytics = self._ultralytics or require_ultralytics()
        try:
            model = ultralytics.YOLO(str(path))
        except Exception as exc:  # noqa: BLE001 - reported to the operator
            raise VisionError(
                f"Ultralytics could not load {path}: {exc}",
                user_message=(
                    "This weights file could not be loaded. It may be corrupt, "
                    "or incompatible with the installed Ultralytics version."
                ),
            ) from exc

        names = getattr(model, "names", {})
        self._class_names = {int(key): str(value) for key, value in dict(names).items()}
        self._model = model
        self._resolve_device()

    def close(self) -> None:
        self._model = None
        self._class_names = {}

    def detect(self, frame: Frame) -> DetectionResult:
        started = time.monotonic()
        model = self._model
        if model is None:
            return self._error(frame, started, "YOLO model is not loaded")

        class_id = self.class_id_for_label(self._config.class_label)
        if class_id is None:
            return self._error(
                frame,
                started,
                f"Class '{self._config.class_label}' is not present in this model",
            )
        return self._predict(frame, model, started, classes=[class_id])

    def detect_all_classes(self, frame: Frame) -> DetectionResult:
        """Detect every class the loaded model knows.

        This is display-only object detection for the Tello Flight tab. It does
        not use the configured target class, so one model can label people,
        furniture and the tracking target together. The result still has
        ``kind=YOLO``; nothing here sends a command or changes flight state.
        """
        started = time.monotonic()
        model = self._model
        if model is None:
            return self._error(frame, started, "YOLO model is not loaded")
        return self._predict(frame, model, started, classes=None)

    def _predict(
        self,
        frame: Frame,
        model: Any,
        started: float,
        *,
        classes: list[int] | None,
    ) -> DetectionResult:
        kwargs: dict[str, Any] = {
            "conf": self._config.confidence_threshold,
            "iou": self._config.iou_threshold,
            "device": self._device,
            "verbose": False,
        }
        if classes is not None:
            kwargs["classes"] = classes
        try:
            results = model.predict(frame.image, **kwargs)
        except Exception as exc:  # noqa: BLE001 - throughput of the worker thread
            return self._error(frame, started, f"YOLO inference failed: {exc}")

        boxes = results[0].boxes if results else None
        detections = parse_yolo_boxes(
            boxes,
            self._class_names,
            frame.shape,
            max_detections=self._config.max_detections,
        )
        finished = time.monotonic()
        return DetectionResult(
            detector_name=self.name,
            kind=self.kind,
            detections=detections,
            frame_timestamp=frame.captured_at,
            processed_at=finished,
            latency_ms=(finished - started) * 1000.0,
        )

    # -- helpers -------------------------------------------------------------

    def class_id_for_label(self, label: str) -> int | None:
        for class_id, name in self._class_names.items():
            if name == label:
                return class_id
        return None

    def _resolve_device(self) -> None:
        requested = self._config.device.strip().lower()
        cuda_available = self._cuda_available()
        if requested in ("", "auto"):
            self._device = "cuda:0" if cuda_available else "cpu"
            if cuda_available:
                self._device_note = "CUDA GPU detected"
            elif self._cuda_probe_failed:
                # "No CUDA GPU" is the wrong diagnosis when the probe itself
                # raised: the machine may well have one and the install is broken.
                self._device_note = (
                    "The CUDA probe failed (see the log); running on CPU"
                )
            else:
                self._device_note = "No CUDA GPU: running on CPU"
            return
        if requested.startswith("cuda") and not cuda_available:
            self._device = "cpu"
            self._device_note = "CUDA was requested but is unavailable; falling back to CPU"
            return
        self._device = requested
        self._device_note = f"Using {requested}"

    def _cuda_available(self) -> bool:
        torch = self._torch
        if torch is None:
            try:
                import importlib

                torch = importlib.import_module("torch")
            except ImportError:
                return False
        try:
            return bool(torch.cuda.is_available())
        except Exception as exc:  # noqa: BLE001 - a broken CUDA install must not crash detection
            # Detection keeps working on the CPU, but this is an environment
            # fault, not a machine without a GPU. Log it and say so in the note
            # instead of reporting the absence of hardware.
            self._cuda_probe_failed = True
            _log.warning(
                "The CUDA probe failed; YOLO will run on the CPU",
                extra={"context": {"error": str(exc)}},
                exc_info=exc,
            )
            return False

    def _error(self, frame: Frame, started: float, message: str) -> DetectionResult:
        return DetectionResult(
            detector_name=self.name,
            kind=self.kind,
            frame_timestamp=frame.captured_at,
            processed_at=started,
            error=message,
        )
