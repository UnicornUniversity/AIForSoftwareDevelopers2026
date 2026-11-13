"""Message-box answers: PySide6 returns the chosen button as a plain int.

A regression here is silent and severe: every confirmation in the application
(execute mission, execute preset, take off, land, arm autonomy) would answer
"No" no matter which button the operator pressed.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from drone_vision_lab.ui import widgets


def test_yes_is_recognised_whether_it_arrives_as_an_int_or_as_the_enum():
    # The running app receives the int form from QMessageBox.warning/question.
    assert widgets.is_yes(int(QMessageBox.StandardButton.Yes))
    assert widgets.is_yes(QMessageBox.StandardButton.Yes)


def test_every_other_answer_is_not_yes():
    assert widgets.is_yes(int(QMessageBox.StandardButton.No)) is False
    assert widgets.is_yes(QMessageBox.StandardButton.No) is False
    assert widgets.is_yes(None) is False
