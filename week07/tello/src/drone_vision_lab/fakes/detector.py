"""Scripted detector used by tests and by the empty-state UI.

It returns whatever detections it was configured with, which makes it possible
to test comparison views, partial failures and tracking decisions without any
model runtime.
"""

from __future__ import annotations

import time

from ..domain import Detection, DetectionResult, DetectorKind, Frame

__all__ = ["FakeDetector"]


class FakeDetector:
    """Configurable detector. Never loads a model."""

    def __init__(
        self,
        *,
        name: str = "Fake detector",
        kind: DetectorKind = DetectorKind.OPENCV,
        detections: tuple[Detection, ...] = (),
        error: str | None = None,
        latency_ms: float = 1.0,
        fail_on_load: bool = False,
    ) -> None:
        self._name = name
        self._kind = kind
        self._detections = detections
        self._error = error
        self._latency_ms = latency_ms
        self._fail_on_load = fail_on_load
        self._ready = False
        self._frames_seen = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def kind(self) -> DetectorKind:
        return self._kind

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def frames_seen(self) -> int:
        return self._frames_seen

    def set_detections(self, detections: tuple[Detection, ...]) -> None:
        self._detections = detections

    def set_error(self, error: str | None) -> None:
        self._error = error

    def load(self) -> None:
        if self._fail_on_load:
            raise RuntimeError(f"{self._name} failed to load (simulated)")
        self._ready = True

    def detect(self, frame: Frame) -> DetectionResult:
        return self._result(frame)

    def detect_all_classes(self, frame: Frame) -> DetectionResult:
        """The fake has no class filter, so this is the same scripted result."""
        return self._result(frame)

    def _result(self, frame: Frame) -> DetectionResult:
        started = time.monotonic()
        self._frames_seen += 1
        if not self._ready:
            return DetectionResult(
                detector_name=self._name,
                kind=self._kind,
                frame_timestamp=frame.captured_at,
                processed_at=started,
                error="Detector is not loaded",
            )
        return DetectionResult(
            detector_name=self._name,
            kind=self._kind,
            detections=() if self._error else self._detections,
            frame_timestamp=frame.captured_at,
            processed_at=started,
            latency_ms=self._latency_ms,
            error=self._error,
        )

    def close(self) -> None:
        self._ready = False
