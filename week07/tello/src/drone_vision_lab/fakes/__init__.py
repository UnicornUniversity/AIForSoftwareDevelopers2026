"""Fake and simulated implementations of every interface.

The application ships with these by default so it can start, be demonstrated
and be tested with no drone, no GPU, no Ollama service and no display.
"""

from .detector import FakeDetector
from .drone import FakeDroneAdapter, RecordedCommand
from .gamepad import FakeGamepad
from .storage import InMemoryProfileRepository, InMemoryResultsRepository
from .video import SyntheticVideoSource

__all__ = [
    "FakeDetector",
    "FakeDroneAdapter",
    "FakeGamepad",
    "InMemoryProfileRepository",
    "InMemoryResultsRepository",
    "RecordedCommand",
    "SyntheticVideoSource",
]
