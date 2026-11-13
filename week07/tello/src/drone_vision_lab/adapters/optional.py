"""Optional dependency loading.

The application must start and stay usable when OpenCV, Ultralytics, pygame or
PyAV are missing. Each helper imports lazily and raises a typed application
error whose ``user_message`` tells the operator which extra to install.
"""

from __future__ import annotations

import importlib
from types import ModuleType

from ..errors import HardwareUnavailableError, VisionError

__all__ = ["require_av", "require_cv2", "require_pygame", "require_ultralytics"]


def require_cv2() -> ModuleType:
    try:
        return importlib.import_module("cv2")
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise VisionError(
            "OpenCV is not installed",
            user_message=(
                "OpenCV is not installed. Install the vision extra with:\n"
                '  pip install -e ".[vision]"'
            ),
        ) from exc


def require_ultralytics() -> ModuleType:
    try:
        return importlib.import_module("ultralytics")
    except ImportError as exc:
        raise VisionError(
            "Ultralytics is not installed",
            user_message=(
                "The YOLO detector needs Ultralytics. Install it with:\n"
                '  pip install -e ".[yolo]"'
            ),
        ) from exc


def require_pygame() -> ModuleType:
    try:
        return importlib.import_module("pygame")
    except ImportError as exc:
        raise HardwareUnavailableError(
            "pygame is not installed",
            user_message=(
                "Gamepad support needs pygame. Install it with:\n"
                '  pip install -e ".[hardware]"'
            ),
        ) from exc


def require_av() -> ModuleType:
    try:
        return importlib.import_module("av")
    except ImportError as exc:
        raise HardwareUnavailableError(
            "PyAV is not installed",
            user_message=(
                "Live Tello video needs PyAV for H.264 decoding. Install it with:\n"
                '  pip install -e ".[hardware]"'
            ),
        ) from exc
