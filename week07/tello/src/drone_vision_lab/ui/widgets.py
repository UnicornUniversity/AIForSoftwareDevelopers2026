"""Small reusable widgets and UI helpers.

Kept deliberately plain: the point of these screens is that the operator can
read the state at a glance from the back of a classroom.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..errors import user_message

__all__ = [
    "EmptyState",
    "SectionTitle",
    "StatusPill",
    "fit_initial_size",
    "is_yes",
    "show_error",
]

_log = logging.getLogger(__name__)

_LEVEL_COLORS = {
    "ok": "#1a7f37",
    "warn": "#b54708",
    "error": "#b42318",
    "idle": "#5b6470",
}


class SectionTitle(QLabel):
    """Bold heading used at the top of each tab."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        font = self.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        self.setFont(font)


class StatusPill(QLabel):
    """Coloured one-word status badge with a longer tooltip."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(110)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_status(text, "idle")

    def set_status(self, text: str, level: str = "idle", tooltip: str = "") -> None:
        color = _LEVEL_COLORS.get(level, _LEVEL_COLORS["idle"])
        self.setText(text)
        self.setStyleSheet(
            f"QLabel {{ color: white; background-color: {color};"
            f" border-radius: 8px; padding: 2px 10px; font-weight: 600; }}"
        )
        self.setToolTip(tooltip or text)


class EmptyState(QWidget):
    """Explains what is missing and what the operator should do next."""

    def __init__(
        self,
        title: str,
        body: str,
        steps: tuple[str, ...] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        heading = QLabel(title)
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        heading.setWordWrap(True)
        layout.addWidget(heading)

        description = QLabel(body)
        description.setWordWrap(True)
        description.setStyleSheet("color: #5b6470;")
        layout.addWidget(description)

        for index, step in enumerate(steps, start=1):
            item = QLabel(f"{index}.  {step}")
            item.setWordWrap(True)
            layout.addWidget(item)


class Separator(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFrameShadow(QFrame.Shadow.Sunken)


def fit_initial_size(
    widget: QWidget, width: int, height: int, *, factor: float = 0.9
) -> None:
    """Resize a window to ``width`` x ``height``, but never fill the display.

    On a scaled laptop panel the logical screen can be much smaller than the
    requested size. Clamping to a fraction of the available area keeps the
    window resizable and leaves room for the desktop around it.
    """
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        widget.resize(width, height)
        return
    available = screen.availableGeometry()
    widget.resize(
        min(width, int(available.width() * factor)),
        min(height, int(available.height() * factor)),
    )


def is_yes(answer: object) -> bool:
    """True when a message-box answer is Yes, whether it arrives as int or enum.

    ``QMessageBox.warning(...)`` returns the chosen standard button as a plain
    ``int`` in PySide6 (``Yes`` is ``16384``), not as the ``StandardButton``
    member. Comparing with ``is`` therefore never matched in the running app,
    even though a test that stubs the dialog with the enum member did. Compare
    by value through this one helper.
    """
    return answer == QMessageBox.StandardButton.Yes


def show_error(parent: QWidget | None, title: str, error: BaseException | str) -> None:
    """Log the failure and show the user-facing part of it."""
    message = user_message(error) if isinstance(error, BaseException) else error
    if isinstance(error, BaseException):
        _log.error("UI error reported: %s", title, exc_info=error)
    else:
        _log.error("UI error reported: %s | %s", title, message)
    QMessageBox.critical(parent, title, message)
