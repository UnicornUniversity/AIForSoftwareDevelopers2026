"""Selection preview: the drawn calibration box must stay visible after release."""

from __future__ import annotations

import time

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from drone_vision_lab.domain import Frame  # noqa: E402
from drone_vision_lab.ui.selection_view import SelectionVideoView  # noqa: E402


def _frame(width: int = 320, height: int = 240) -> Frame:
    image = np.full((height, width, 3), 30, dtype=np.uint8)
    return Frame(image=image, captured_at=time.monotonic(), source_id="test", index=0)


def _view(width: int = 320, height: int = 240) -> SelectionVideoView:
    view = SelectionVideoView()
    view.resize(width, height)
    view.show_frame(_frame())
    view.show()
    return view


def _send(
    view: SelectionVideoView,
    event_type: QEvent.Type,
    pos: QPoint,
    *,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
) -> None:
    QApplication.sendEvent(
        view,
        QMouseEvent(
            event_type,
            QPointF(pos),
            QPointF(view.mapToGlobal(pos)),
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def _drag(view: SelectionVideoView, start: QPoint, end: QPoint) -> None:
    _send(
        view,
        QEvent.Type.MouseButtonPress,
        start,
        button=Qt.MouseButton.LeftButton,
        buttons=Qt.MouseButton.LeftButton,
    )
    _send(
        view,
        QEvent.Type.MouseMove,
        QPoint((start.x() + end.x()) // 2, (start.y() + end.y()) // 2),
        button=Qt.MouseButton.NoButton,
        buttons=Qt.MouseButton.LeftButton,
    )
    _send(
        view,
        QEvent.Type.MouseButtonRelease,
        end,
        button=Qt.MouseButton.LeftButton,
        buttons=Qt.MouseButton.NoButton,
    )


def test_dragging_keeps_the_box_visible_after_release(qapp):
    view = _view()

    _drag(view, QPoint(50, 40), QPoint(150, 140))

    # QRect counts both corner pixels, so a 100 px drag spans 101 columns.
    assert view.selection == (50, 40, 101, 101)
    assert not view._rubber.isHidden()  # noqa: SLF001 - the band is the whole point
    assert view._rubber.geometry() == QRect(50, 40, 101, 101)  # noqa: SLF001


def test_a_click_without_a_drag_clears_the_box(qapp):
    view = _view()
    _drag(view, QPoint(50, 40), QPoint(150, 140))

    _drag(view, QPoint(60, 50), QPoint(60, 50))

    assert view.selection is None
    assert view._rubber.isHidden()  # noqa: SLF001


def test_set_selection_draws_the_box(qapp):
    view = _view()

    view.set_selection((100, 70, 80, 80))

    assert not view._rubber.isHidden()  # noqa: SLF001
    assert view._rubber.geometry() == QRect(100, 70, 80, 80)  # noqa: SLF001


def test_clearing_the_selection_hides_the_box(qapp):
    view = _view()
    view.set_selection((100, 70, 80, 80))

    view.clear_selection()

    assert view.selection is None
    assert view._rubber.isHidden()  # noqa: SLF001


def test_a_selection_is_redrawn_at_the_new_scale_after_a_resize(qapp):
    view = _view(640, 480)
    view.set_selection((100, 70, 80, 80))
    assert view._rubber.geometry() == QRect(200, 140, 160, 160)  # noqa: SLF001

    view.resize(320, 240)
    qapp.processEvents()

    # Half the widget means half the scale, so the same frame rectangle halves.
    assert view._rubber.geometry() == QRect(100, 70, 80, 80)  # noqa: SLF001
    assert not view._rubber.isHidden()  # noqa: SLF001
