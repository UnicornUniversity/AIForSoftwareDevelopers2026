"""Video view with a rubber-band selection, used for colour calibration.

Selection coordinates are reported in frame pixels, not widget pixels, so the
calibration code never has to know how the preview was scaled.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import QRubberBand

from ..domain import Frame
from .video_view import VideoView

__all__ = ["SelectionVideoView"]


class SelectionVideoView(VideoView):
    selection_changed = Signal(object)  # tuple[int, int, int, int] | None

    def __init__(self, placeholder: str = "No frame", parent=None) -> None:
        super().__init__(placeholder, parent)
        self._rubber = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self._origin = QPoint()
        self._selection: tuple[int, int, int, int] | None = None
        self._frame_size: tuple[int, int] = (0, 0)
        self._offset = QPoint(0, 0)
        self._scale = 1.0
        self._dragging = False

    @property
    def selection(self) -> tuple[int, int, int, int] | None:
        """``(x, y, width, height)`` in frame pixels, or ``None``."""
        return self._selection

    def clear_selection(self) -> None:
        self._selection = None
        self._dragging = False
        self._rubber.hide()
        self.selection_changed.emit(None)

    def set_selection(self, rect: tuple[int, int, int, int] | None) -> None:
        """Set the selection programmatically, in frame pixels."""
        self._selection = rect
        self._show_selection()
        self.selection_changed.emit(rect)

    def show_frame(self, frame: Frame) -> None:
        self._frame_size = frame.shape
        super().show_frame(frame)

    # -- geometry ------------------------------------------------------------

    def _render(self) -> None:
        super()._render()
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull() or not self._frame_size[0]:
            return
        self._scale = pixmap.width() / float(self._frame_size[0])
        self._offset = QPoint(
            (self.width() - pixmap.width()) // 2,
            (self.height() - pixmap.height()) // 2,
        )
        if not self._dragging:
            # The preview scales with the window, so redraw a settled selection
            # at the new scale. A drag in progress owns the band until release.
            self._show_selection()

    def _to_frame_rect(self, rect: QRect) -> tuple[int, int, int, int] | None:
        if self._scale <= 0.0 or not self._frame_size[0]:
            return None
        width, height = self._frame_size
        x = int((rect.x() - self._offset.x()) / self._scale)
        y = int((rect.y() - self._offset.y()) / self._scale)
        w = int(rect.width() / self._scale)
        h = int(rect.height() / self._scale)
        x = max(0, min(x, width - 1))
        y = max(0, min(y, height - 1))
        w = max(0, min(w, width - x))
        h = max(0, min(h, height - y))
        if w < 2 or h < 2:
            return None
        return x, y, w, h

    def _to_widget_rect(self, rect: tuple[int, int, int, int]) -> QRect:
        """Map a frame-pixel rectangle back onto the preview, for the rubber band."""
        if self._scale <= 0.0:
            return QRect()
        x, y, w, h = rect
        return QRect(
            int(round(self._offset.x() + x * self._scale)),
            int(round(self._offset.y() + y * self._scale)),
            int(round(w * self._scale)),
            int(round(h * self._scale)),
        )

    def _show_selection(self) -> None:
        """Draw the settled selection, so the operator sees what will be sampled."""
        if self._selection is None:
            self._rubber.hide()
            return
        self._rubber.setGeometry(self._to_widget_rect(self._selection))
        self._rubber.show()

    # -- mouse ---------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() is not Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self._dragging = True
        self._origin = event.position().toPoint()
        self._rubber.setGeometry(QRect(self._origin, QSize()))
        self._rubber.show()
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if not self._dragging:
            return super().mouseMoveEvent(event)
        rect = QRect(self._origin, event.position().toPoint()).normalized()
        self._rubber.setGeometry(rect)
        return None

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() is not Qt.MouseButton.LeftButton or not self._dragging:
            return super().mouseReleaseEvent(event)
        self._dragging = False
        # Use the release position, not the band geometry: the last mouse-move
        # may lag behind the point where the button came up.
        rect = QRect(self._origin, event.position().toPoint()).normalized()
        self._selection = self._to_frame_rect(rect)
        if self._selection is None:
            self._rubber.hide()
        else:
            # Snap to the exact sampled rectangle: the dragged band may extend
            # past the frame edge and be clamped when converted to frame pixels.
            self._show_selection()
        self.selection_changed.emit(self._selection)
        return None
