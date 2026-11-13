"""Green target overlay shared by the advisory tab and the apple preset.

The Computer Vision Lab and Tello Flight draw YOLO boxes blue. This overlay is
deliberately separate: the rehearsal paints the target **green** so an operator
can tell at a glance that the box belongs to the pursuit demo, and adds the
centre line, the deadband band, an error arrow and the advisory banner.
:func:`render_target_overlay` draws only the green boxes; the apple-recognition
preset uses it while the aircraft hovers and no tracking decision is being made.

Layout is a pure function, so tests assert geometry and wording without
inspecting pixels.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from ..domain import BoundingBox, DetectionResult, Frame
from ..pursuit import PursuitAction, PursuitDecision
from ..tracking import DEFAULT_TRACKING_SETTINGS

__all__ = [
    "GuidanceRender",
    "TARGET_COLOR",
    "action_color",
    "deadband_bounds",
    "guidance_layout",
    "render_guidance",
    "render_target_overlay",
    "select_target_box",
]

TARGET_COLOR = "#34c759"
_CENTER_COLOR = "#f2f2f2"
_DEADBAND_FILL = QColor(52, 199, 89, 38)

_ACTION_COLORS = {
    PursuitAction.IDLE: "#5b6470",
    PursuitAction.CENTERED: TARGET_COLOR,
    PursuitAction.YAW_LEFT: "#f5a524",
    PursuitAction.YAW_RIGHT: "#f5a524",
    PursuitAction.HOLDING: "#f5a524",
    PursuitAction.NO_TARGET: "#5b6470",
    PursuitAction.STOPPED: "#b42318",
}


@dataclass(frozen=True, slots=True)
class GuidanceRender:
    """What the overlay drew, in frame pixels."""

    width: int
    height: int
    target_box: BoundingBox | None
    target_color: str
    center_x: float
    deadband_left: float
    deadband_right: float
    error_px: float | None
    action: PursuitAction
    banner: str


def action_color(action: PursuitAction) -> str:
    return _ACTION_COLORS.get(action, _ACTION_COLORS[PursuitAction.IDLE])


def deadband_bounds(
    width: int,
    deadband: float = DEFAULT_TRACKING_SETTINGS.deadband,
) -> tuple[float, float]:
    """Pixel ``(left, right)`` edges of the deadband around the centre line."""
    if width <= 0:
        return 0.0, 0.0
    return width * (0.5 - deadband), width * (0.5 + deadband)


def select_target_box(result: DetectionResult | None) -> BoundingBox | None:
    """The largest normalized detection, matching the advisor's choice."""
    if result is None or result.failed:
        return None
    boxes = [
        detection.box for detection in result.detections if detection.box.normalized
    ]
    if not boxes:
        return None
    return max(boxes, key=lambda box: box.area)


def guidance_layout(
    frame_size: tuple[int, int],
    result: DetectionResult | None,
    decision: PursuitDecision,
    *,
    deadband: float = DEFAULT_TRACKING_SETTINGS.deadband,
) -> GuidanceRender:
    width, height = frame_size
    target_box = select_target_box(result)
    left, right = deadband_bounds(width, deadband)
    center_x = width * 0.5
    error_px: float | None = None
    if decision.error is not None:
        error_px = decision.error * width
    elif target_box is not None:
        error_px = (target_box.center[0] - 0.5) * width
    return GuidanceRender(
        width=width,
        height=height,
        target_box=target_box,
        target_color=TARGET_COLOR,
        center_x=center_x,
        deadband_left=left,
        deadband_right=right,
        error_px=error_px,
        action=decision.action,
        banner=decision.banner,
    )


def render_guidance(
    frame: Frame,
    result: DetectionResult | None,
    decision: PursuitDecision,
    *,
    deadband: float = DEFAULT_TRACKING_SETTINGS.deadband,
) -> tuple[QImage, GuidanceRender]:
    """Draw the guidance overlay and return the image with its layout."""
    from .video_view import bgr_to_qimage

    image = bgr_to_qimage(frame.image).copy()
    layout = guidance_layout(frame.shape, result, decision, deadband=deadband)
    if layout.width <= 0 or layout.height <= 0:
        return image, layout

    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _draw_deadband(painter, layout)
        _draw_target_boxes(
            painter,
            result,
            layout.width,
            layout.height,
            chosen=layout.target_box,
        )
        _draw_error_arrow(painter, layout, deadband)
        _draw_banner(painter, layout)
    finally:
        painter.end()
    return image, layout


def render_target_overlay(
    frame: Frame,
    result: DetectionResult | None,
) -> QImage:
    """Draw only the green target boxes, for a camera view with no advisory.

    The apple-recognition preset uses this while the aircraft hovers (it has no
    position hold): it marks the configured YOLO class without the deadband, error
    arrow or advisory banner, because no tracking decision is being made.
    """
    from .video_view import bgr_to_qimage

    image = bgr_to_qimage(frame.image).copy()
    if image.width() <= 0 or image.height() <= 0:
        return image
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _draw_target_boxes(
            painter,
            result,
            image.width(),
            image.height(),
            chosen=select_target_box(result),
        )
    finally:
        painter.end()
    return image


# -- drawing -----------------------------------------------------------------


def _draw_deadband(painter: QPainter, layout: GuidanceRender) -> None:
    painter.fillRect(
        QRectF(
            layout.deadband_left,
            0.0,
            layout.deadband_right - layout.deadband_left,
            float(layout.height),
        ),
        _DEADBAND_FILL,
    )
    pen = QPen(QColor(_CENTER_COLOR))
    pen.setWidth(1)
    pen.setStyle(Qt.PenStyle.DashLine)
    painter.setPen(pen)
    painter.drawLine(
        int(layout.center_x), 0, int(layout.center_x), layout.height
    )


def _draw_target_boxes(
    painter: QPainter,
    result: DetectionResult | None,
    width: int,
    height: int,
    *,
    chosen: BoundingBox | None,
) -> None:
    if result is None or result.failed:
        return
    for detection in result.detections:
        if not detection.box.normalized:
            continue
        is_chosen = chosen is not None and detection.box == chosen
        box = detection.box.to_pixels((width, height))
        pen = QPen(QColor(TARGET_COLOR))
        pen.setWidth(3 if is_chosen else 1)
        painter.setPen(pen)
        painter.drawRect(QRectF(box.x, box.y, box.w, box.h))
        if is_chosen:
            score = (
                f" {detection.confidence:.2f}"
                if detection.confidence is not None
                else ""
            )
            painter.setPen(QPen(QColor(TARGET_COLOR)))
            painter.drawText(
                int(box.x), max(10, int(box.y) - 4), f"{detection.label}{score}"
            )


def _draw_error_arrow(
    painter: QPainter,
    layout: GuidanceRender,
    deadband: float,
) -> None:
    if layout.error_px is None or layout.action is PursuitAction.STOPPED:
        return
    if layout.action is PursuitAction.NO_TARGET:
        return
    target_x = layout.center_x + layout.error_px
    y = float(layout.height) * 0.85
    inside = abs(layout.error_px) <= deadband * layout.width
    pen = QPen(QColor(TARGET_COLOR if inside else "#f5a524"))
    pen.setWidth(2)
    painter.setPen(pen)
    painter.drawLine(int(layout.center_x), int(y), int(target_x), int(y))
    painter.drawLine(int(target_x), int(y), int(target_x) - 6, int(y) - 4)
    painter.drawLine(int(target_x), int(y), int(target_x) - 6, int(y) + 4)


def _draw_banner(painter: QPainter, layout: GuidanceRender) -> None:
    color = action_color(layout.action)
    banner_height = max(18.0, min(30.0, layout.height / 6.0))
    fill = QColor(color)
    fill.setAlpha(220)
    painter.fillRect(QRectF(0.0, 0.0, float(layout.width), banner_height), fill)
    font = painter.font()
    font.setPixelSize(max(9, min(14, int(banner_height) - 6)))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QPen(QColor("white")))
    painter.drawText(
        QRectF(6.0, 0.0, layout.width - 12.0, banner_height),
        int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
        layout.banner,
    )
