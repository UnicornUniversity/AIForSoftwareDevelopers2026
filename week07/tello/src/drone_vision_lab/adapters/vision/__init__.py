"""Vision adapters: OpenCV colour thresholding, then YOLO and the Ollama VLM."""

from .opencv_calibration import (
    auto_estimate_hsv_range,
    estimate_hsv_range,
    sample_patch_statistics,
)
from .opencv_detector import (
    HsvRange,
    OpenCvDetectorConfig,
    OpenCvProcessing,
    OpenCvTargetDetector,
    build_mask,
)
from .yolo_detector import YoloDetector, YoloDetectorConfig, parse_yolo_boxes

__all__ = [
    "HsvRange",
    "auto_estimate_hsv_range",
    "OpenCvDetectorConfig",
    "OpenCvProcessing",
    "OpenCvTargetDetector",
    "YoloDetector",
    "YoloDetectorConfig",
    "build_mask",
    "estimate_hsv_range",
    "parse_yolo_boxes",
    "sample_patch_statistics",
]
