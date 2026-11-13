"""OpenCV colour-threshold detector.

Finds a coloured object (the classroom tennis ball or an apple) by thresholding
in HSV space, cleaning the mask morphologically and taking the largest
contours. Everything is driven by a :class:`OpenCvDetectorConfig`, which is
what the calibration workflow produces and what a profile stores.

There is deliberately no confidence value: thresholding has no defensible
probability. The detector reports a mask fill ratio, clearly named as a shape
metric, and nothing that could be mistaken for a calibrated score.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from types import ModuleType
from typing import Any

import numpy as np

from ...domain import BoundingBox, Detection, DetectionResult, DetectorKind, Frame
from ...errors import ConfigurationError
from ..optional import require_cv2

__all__ = [
    "HsvRange",
    "OpenCvDetectorConfig",
    "OpenCvProcessing",
    "OpenCvTargetDetector",
    "build_mask",
    "contours_to_detections",
]

CONFIG_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class HsvRange:
    """Inclusive HSV bounds in OpenCV units: H 0-179, S 0-255, V 0-255.

    ``lower_h`` greater than ``upper_h`` means the hue selection wraps through
    red (for example ``165 -> 10``). That is a normal, expected case.
    """

    lower: tuple[int, int, int]
    upper: tuple[int, int, int]

    def __post_init__(self) -> None:
        self._validate("lower", self.lower, hue_max=179)
        self._validate("upper", self.upper, hue_max=179)

    @staticmethod
    def _validate(name: str, value: tuple[int, int, int], *, hue_max: int) -> None:
        if len(value) != 3:
            raise ValueError(f"HSV {name} needs three components")
        h, s, v = value
        if not 0 <= h <= hue_max:
            raise ValueError(f"HSV {name} hue must be within 0..{hue_max}, got {h}")
        if not 0 <= s <= 255 or not 0 <= v <= 255:
            raise ValueError(f"HSV {name} saturation/value must be within 0..255")

    @property
    def wraps(self) -> bool:
        return self.lower[0] > self.upper[0]

    def to_dict(self) -> dict[str, Any]:
        return {"lower": list(self.lower), "upper": list(self.upper)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HsvRange:
        try:
            return cls(tuple(data["lower"]), tuple(data["upper"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigurationError(
                f"Invalid HSV range in profile: {data!r}",
                user_message="The saved colour calibration is invalid and must be redone.",
            ) from exc


@dataclass(frozen=True, slots=True)
class OpenCvDetectorConfig:
    """Everything the OpenCV detector needs, and nothing else."""

    ranges: tuple[HsvRange, ...] = ()
    min_area_fraction: float = 0.002
    blur_kernel: int = 5
    morph_open_kernel: int = 0
    morph_close_kernel: int = 3
    max_detections: int = 5
    label: str = "green_tennis_ball"

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_area_fraction < 1.0:
            raise ValueError("min_area_fraction must be within [0, 1)")
        for name in ("blur_kernel", "morph_open_kernel", "morph_close_kernel"):
            value = getattr(self, name)
            if value != 0 and (value < 3 or value % 2 == 0):
                raise ValueError(f"{name} must be 0 or an odd number of at least 3")
        if self.max_detections < 1:
            raise ValueError("max_detections must be at least 1")

    @property
    def calibrated(self) -> bool:
        return bool(self.ranges)

    def with_ranges(self, *ranges: HsvRange) -> OpenCvDetectorConfig:
        return replace(self, ranges=tuple(ranges))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "label": self.label,
            "ranges": [hsv.to_dict() for hsv in self.ranges],
            "min_area_fraction": self.min_area_fraction,
            "blur_kernel": self.blur_kernel,
            "morph_open_kernel": self.morph_open_kernel,
            "morph_close_kernel": self.morph_close_kernel,
            "max_detections": self.max_detections,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpenCvDetectorConfig:
        version = data.get("schema_version")
        if version != CONFIG_SCHEMA_VERSION:
            raise ConfigurationError(
                f"Unsupported OpenCV config schema version {version!r}",
                user_message="This colour calibration was saved by an incompatible version.",
            )
        try:
            return cls(
                ranges=tuple(HsvRange.from_dict(item) for item in data.get("ranges", [])),
                min_area_fraction=float(data.get("min_area_fraction", 0.002)),
                blur_kernel=int(data.get("blur_kernel", 5)),
                morph_open_kernel=int(data.get("morph_open_kernel", 0)),
                morph_close_kernel=int(data.get("morph_close_kernel", 3)),
                max_detections=int(data.get("max_detections", 5)),
                label=str(data.get("label", "green_tennis_ball")),
            )
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(
                f"Invalid OpenCV calibration: {exc}",
                user_message="The saved colour calibration is invalid and must be redone.",
            ) from exc


@dataclass(frozen=True, slots=True)
class OpenCvProcessing:
    """Mask and detections from one frame, for the calibration preview."""

    mask: np.ndarray
    result: DetectionResult


def build_mask(
    image: np.ndarray,
    config: OpenCvDetectorConfig,
    *,
    cv2_module: ModuleType | None = None,
) -> np.ndarray:
    """Return the binary mask for ``image`` (BGR) under ``config``."""
    cv2 = cv2_module or require_cv2()
    if not config.ranges:
        return np.zeros(image.shape[:2], dtype=np.uint8)

    working = image
    if config.blur_kernel >= 3:
        working = cv2.GaussianBlur(image, (config.blur_kernel, config.blur_kernel), 0)
    hsv = cv2.cvtColor(working, cv2.COLOR_BGR2HSV)

    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    for hsv_range in config.ranges:
        _, sat_low, val_low = hsv_range.lower
        _, sat_high, val_high = hsv_range.upper
        if hsv_range.wraps:
            mask |= cv2.inRange(
                hsv,
                np.array([hsv_range.lower[0], sat_low, val_low], dtype=np.uint8),
                np.array([179, sat_high, val_high], dtype=np.uint8),
            )
            mask |= cv2.inRange(
                hsv,
                np.array([0, sat_low, val_low], dtype=np.uint8),
                np.array([hsv_range.upper[0], sat_high, val_high], dtype=np.uint8),
            )
        else:
            mask |= cv2.inRange(
                hsv,
                np.array(hsv_range.lower, dtype=np.uint8),
                np.array(hsv_range.upper, dtype=np.uint8),
            )

    if config.morph_open_kernel >= 3:
        kernel = np.ones((config.morph_open_kernel, config.morph_open_kernel), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    if config.morph_close_kernel >= 3:
        kernel = np.ones((config.morph_close_kernel, config.morph_close_kernel), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def contours_to_detections(
    mask: np.ndarray,
    config: OpenCvDetectorConfig,
    *,
    cv2_module: ModuleType | None = None,
) -> tuple[Detection, ...]:
    """Convert a mask into the largest, sufficiently large contours."""
    cv2 = cv2_module or require_cv2()
    height, width = mask.shape[:2]
    min_area = config.min_area_fraction * float(width * height)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates: list[tuple[float, int, int, int, int]] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < min_area or area <= 0.0:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if w <= 0 or h <= 0:
            continue
        candidates.append((area, int(x), int(y), int(w), int(h)))

    candidates.sort(key=lambda item: item[0], reverse=True)
    detections: list[Detection] = []
    for area, x, y, w, h in candidates[: config.max_detections]:
        box = BoundingBox(
            x=min(1.0, x / width),
            y=min(1.0, y / height),
            w=min(1.0 - min(1.0, x / width), w / width),
            h=min(1.0 - min(1.0, y / height), h / height),
            normalized=True,
        )
        fill_ratio = area / float(w * h)
        detections.append(
            Detection(
                label=config.label,
                box=box,
                confidence=None,
                metrics={"mask_area_px": area, "fill_ratio": fill_ratio},
            )
        )
    return tuple(detections)


class OpenCvTargetDetector:
    """Colour-threshold detector behind the project's :class:`Detector` contract."""

    def __init__(self, config: OpenCvDetectorConfig | None = None) -> None:
        self._config = config or OpenCvDetectorConfig()
        self._cv2: ModuleType | None = None

    @property
    def name(self) -> str:
        return "OpenCV colour threshold"

    @property
    def kind(self) -> DetectorKind:
        return DetectorKind.OPENCV

    @property
    def ready(self) -> bool:
        return self._cv2 is not None and self._config.calibrated

    @property
    def config(self) -> OpenCvDetectorConfig:
        return self._config

    def update_config(self, config: OpenCvDetectorConfig) -> None:
        self._config = config

    def load(self) -> None:
        self._cv2 = require_cv2()

    def close(self) -> None:
        self._cv2 = None

    def detect(self, frame: Frame) -> DetectionResult:
        return self.process(frame).result

    def process(self, frame: Frame) -> OpenCvProcessing:
        """Return both the mask and the detections; used by the calibration preview."""
        started = time.monotonic()
        if self._cv2 is None:
            return OpenCvProcessing(
                mask=np.zeros(frame.image.shape[:2], dtype=np.uint8),
                result=self._error(frame, started, "OpenCV detector is not loaded"),
            )
        if not self._config.calibrated:
            return OpenCvProcessing(
                mask=np.zeros(frame.image.shape[:2], dtype=np.uint8),
                result=self._error(frame, started, "No colour calibration saved"),
            )
        try:
            mask = build_mask(frame.image, self._config, cv2_module=self._cv2)
            detections = contours_to_detections(mask, self._config, cv2_module=self._cv2)
        except Exception as exc:  # noqa: BLE001 - reported, never raised to the UI thread
            return OpenCvProcessing(
                mask=np.zeros(frame.image.shape[:2], dtype=np.uint8),
                result=self._error(frame, started, f"OpenCV detection failed: {exc}"),
            )
        finished = time.monotonic()
        return OpenCvProcessing(
            mask=mask,
            result=DetectionResult(
                detector_name=self.name,
                kind=self.kind,
                detections=detections,
                frame_timestamp=frame.captured_at,
                processed_at=finished,
                latency_ms=(finished - started) * 1000.0,
            ),
        )

    def _error(self, frame: Frame, started: float, message: str) -> DetectionResult:
        return DetectionResult(
            detector_name=self.name,
            kind=self.kind,
            frame_timestamp=frame.captured_at,
            processed_at=started,
            error=message,
        )
