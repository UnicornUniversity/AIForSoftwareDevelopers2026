"""Widget that displays BGR frames from the video pipeline."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from ..domain import Frame

__all__ = ["VideoView", "bgr_to_qimage"]


def bgr_to_qimage(image: np.ndarray) -> QImage:
    """Convert an OpenCV BGR frame to a QImage, copying the buffer.

    The copy matters: the NumPy array is reused by the decoder, and a QImage
    that merely wraps it would show torn or stale pixels.
    """
    height, width = image.shape[:2]
    bytes_per_line = 3 * width
    return QImage(
        image.data, width, height, bytes_per_line, QImage.Format.Format_BGR888
    ).copy()


class VideoView(QLabel):
    """Letterboxed preview of the latest frame."""

    def __init__(self, placeholder: str = "No video source loaded", parent=None) -> None:
        super().__init__(parent)
        self._placeholder = placeholder
        self._pixmap: QPixmap | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(
            "QLabel { background-color: #101418; color: #9aa4b2;"
            " border: 1px solid #2b333d; border-radius: 6px; font-size: 14px; }"
        )
        self.setText(placeholder)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        # QLabel derives its hint from the pixmap; that would make the preview
        # demand the last scaled frame size and stop the window from shrinking.
        return QSize(480, 300)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(240, 160)

    def show_frame(self, frame: Frame) -> None:
        self.show_image(bgr_to_qimage(frame.image))

    def show_image(self, image: QImage) -> None:
        """Display an already-composed image (e.g. a frame with overlays)."""
        self._pixmap = QPixmap.fromImage(image)
        self._render()

    def clear(self) -> None:
        self._pixmap = None
        self.setText(self._placeholder)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._render()

    def _render(self) -> None:
        pixmap = self._pixmap
        if pixmap is None:
            return
        if self.width() <= 0 or self.height() <= 0:
            return
        self.setPixmap(
            pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    @property
    def has_frame(self) -> bool:
        return self._pixmap is not None


def make_placeholder(parent: QWidget | None = None) -> VideoView:
    return VideoView(parent=parent)
