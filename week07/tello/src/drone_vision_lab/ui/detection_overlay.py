"""Draw detector results over a frame.

Each algorithm gets one colour, and only that algorithm's boxes use it, so a
comparison image is readable at a glance:

* OpenCV — green, solid
* YOLO — blue, solid
* VLM — amber, dashed, and labelled with the age of the answer

Confidence is printed only when a detector produced one. OpenCV and the VLM
print ``N/A``; inventing a number to fill the column would misrepresent both.
"""

from __future__ import annotations

import time
from collections.abc import Mapping

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from ..domain import DetectionResult, DetectorKind, Frame
from .video_view import bgr_to_qimage

__all__ = ["DISPLAY_NAMES", "KIND_COLORS", "confidence_text", "render_frame"]

DISPLAY_NAMES: dict[DetectorKind, str] = {
    DetectorKind.OPENCV: "OpenCV",
    DetectorKind.YOLO: "YOLO",
    DetectorKind.VLM: "VLM",
}

KIND_COLORS: dict[DetectorKind, str] = {
    DetectorKind.OPENCV: "#34c759",
    DetectorKind.YOLO: "#4aa3ff",
    DetectorKind.VLM: "#f5a524",
}

_DRAW_ORDER = (DetectorKind.OPENCV, DetectorKind.YOLO, DetectorKind.VLM)


def confidence_text(result: DetectionResult) -> str:
    """Confidence column text; never a fabricated score."""
    scores = [d.confidence for d in result.detections if d.confidence is not None]
    if not scores:
        return "N/A"
    return f"{max(scores):.2f}"


def render_frame(
    frame: Frame,
    results: Mapping[DetectorKind, DetectionResult],
    *,
    now: float | None = None,
) -> QImage:
    """Return a new QImage with every supplied result drawn on ``frame``."""
    image = bgr_to_qimage(frame.image).convertToFormat(QImage.Format.Format_ARGB32)
    if image.width() <= 0 or image.height() <= 0:
        return image

    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = image.width(), image.height()
        font = QFont("Segoe UI")
        font.setPixelSize(max(10, min(20, width // 40)))
        font.setBold(True)
        painter.setFont(font)
        line_width = max(2, width // 320)
        timestamp = time.monotonic() if now is None else now
        banner_y = 4

        for kind in _DRAW_ORDER:
            result = results.get(kind)
            if result is None:
                continue
            color = QColor(KIND_COLORS[kind])
            name = DISPLAY_NAMES[kind]

            if result.failed:
                banner_y = _draw_banner(
                    painter,
                    f"{name}: {result.error}",
                    color,
                    width,
                    banner_y,
                )
                continue

            pen = QPen(color, line_width)
            if kind is DetectorKind.VLM:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)

            for detection in result.detections:
                box = detection.box
                rect = QRectF(
                    box.x * width,
                    box.y * height,
                    max(1.0, box.w * width),
                    max(1.0, box.h * height),
                )
                painter.drawRect(rect)

                suffix = ""
                if kind is DetectorKind.VLM:
                    age = max(0.0, timestamp - result.processed_at)
                    suffix = f" · {age:.1f}s old"
                # Use this box's own score. The result-wide maximum would label
                # every class with the best detection's confidence.
                score = (
                    f"{detection.confidence:.2f}"
                    if detection.confidence is not None
                    else "N/A"
                )
                label = f"{name} · {detection.label} · {score}{suffix}"
                _draw_label(painter, label, rect, color, height)
                painter.setPen(pen)

            if kind is DetectorKind.VLM and not result.detections:
                age = max(0.0, timestamp - result.processed_at)
                banner_y = _draw_banner(
                    painter,
                    f"{name}: no target · {age:.1f}s old",
                    color,
                    width,
                    banner_y,
                )
    finally:
        painter.end()
    return image


def _draw_banner(
    painter: QPainter, text: str, color: QColor, width: int, y: int
) -> int:
    metrics = painter.fontMetrics()
    clipped = metrics.elidedText(text, Qt.TextElideMode.ElideRight, width - 8)
    height = metrics.height()
    background = QColor(color)
    background.setAlpha(225)
    painter.fillRect(QRectF(0, y, width, height + 2), background)
    painter.setPen(QColor("#101418"))
    painter.drawText(4, y + height - 2, clipped)
    return y + height + 4


def _draw_label(
    painter: QPainter, text: str, rect: QRectF, color: QColor, height: int
) -> None:
    metrics = painter.fontMetrics()
    text_width = metrics.horizontalAdvance(text)
    text_height = metrics.height()
    top = rect.top() - text_height - 2
    if top < 0:
        top = min(rect.top() + 2, max(0.0, height - text_height))
    background = QColor(color)
    background.setAlpha(215)
    painter.fillRect(QRectF(rect.left(), top, text_width + 8, text_height), background)
    painter.setPen(QColor("#101418"))
    painter.drawText(int(rect.left()) + 4, int(top) + text_height - 3, text)
