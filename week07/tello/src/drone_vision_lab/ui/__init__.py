"""PySide6 presentation layer.

Widgets never construct adapters themselves: everything arrives through
:class:`drone_vision_lab.container.AppServices`.
"""

from .main_window import MainWindow

__all__ = ["MainWindow"]
