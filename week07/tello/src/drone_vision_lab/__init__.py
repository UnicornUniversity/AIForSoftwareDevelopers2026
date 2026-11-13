"""Drone Vision Lab — classroom drone control and computer-vision comparison.

Layout of the package:

``domain``        shared value types (frames, detections, telemetry, commands)
``interfaces``    Protocols every adapter, fake and real implementation satisfies
``fakes``         simulation and test doubles; the defaults for this build
``state``         thread-safe application state model
``config``        identity, paths and conservative safety defaults
``container``     composition root wiring all collaborators together
``ui``            PySide6 presentation layer
``app``           bootstrap and entry point
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
