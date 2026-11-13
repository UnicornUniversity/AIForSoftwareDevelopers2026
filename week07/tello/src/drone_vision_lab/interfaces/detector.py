"""Detector interface.

OpenCV thresholding, YOLO inference and the Ollama VLM all implement this
contract. They differ wildly in latency and in what their output means, so the
contract carries the algorithm ``kind`` and lets confidence be ``None``.

The VLM implementation is analysis-only. Nothing in this interface, and
nothing downstream of it, may feed the flight controller: the tracking
controller accepts only ``DetectorKind.OPENCV`` and ``DetectorKind.YOLO``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain import DetectionResult, DetectorKind, Frame

__all__ = ["Detector", "DetectorStatus", "ObjectDetector"]


class DetectorStatus:
    """Non-instanceable namespace of status strings for UI display."""

    UNLOADED = "unloaded"
    READY = "ready"
    ERROR = "error"


@runtime_checkable
class Detector(Protocol):
    """Contract for one vision algorithm."""

    @property
    def name(self) -> str:
        """Short label shown in the UI, e.g. ``"YOLO11n"``."""

    @property
    def kind(self) -> DetectorKind: ...

    @property
    def ready(self) -> bool:
        """True when ``detect`` can run. Loading is explicit, never automatic."""

    def load(self) -> None:
        """Load models/resources. Raises an application error on failure."""

    def detect(self, frame: Frame) -> DetectionResult:
        """Analyze one frame and return a result.

        Implementations must not raise for ordinary failure (missing target,
        corrupt frame, inference error): they return a ``DetectionResult`` with
        ``error`` set, so a comparison view can show one algorithm failing while
        the others continue.
        """

    def close(self) -> None:
        """Release model/runtime resources. Safe to call repeatedly."""


@runtime_checkable
class ObjectDetector(Detector, Protocol):
    """Detector that can label every class its model knows.

    The Computer Vision Lab uses :meth:`Detector.detect` for one target class.
    The Tello Flight view uses :meth:`detect_all_classes` for general object
    detection. Both are analysis-only: neither has a flight-control path.
    """

    def detect_all_classes(self, frame: Frame) -> DetectionResult:
        """Analyze one frame and return every recognized class."""
