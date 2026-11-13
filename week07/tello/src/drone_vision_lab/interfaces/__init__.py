"""Typed contracts that every adapter, fake and real implementation must satisfy.

Concrete implementations live in ``drone_vision_lab.fakes`` (tests, simulation)
and, from phase 8 onwards, in ``drone_vision_lab.adapters`` (real hardware,
models, services). The UI and application layers depend on these protocols
only, never on a concrete adapter.
"""

from .detector import Detector, DetectorStatus, ObjectDetector
from .drone import DroneAdapter, MovementDirection, RotationDirection
from .gamepad import GamepadAdapter, GamepadState
from .profiles import PROFILE_SCHEMA_VERSION, Profile, ProfileRepository
from .results import (
    EXPERIMENT_SCHEMA_VERSION,
    ExperimentContext,
    ExperimentRecord,
    MetricSample,
    ResultsRepository,
    csv_rows,
    experiment_to_document,
)
from .video import VideoSource, VideoSourceState, VideoSourceStatus

__all__ = [
    "EXPERIMENT_SCHEMA_VERSION",
    "PROFILE_SCHEMA_VERSION",
    "Detector",
    "DetectorStatus",
    "DroneAdapter",
    "ExperimentContext",
    "ExperimentRecord",
    "GamepadAdapter",
    "GamepadState",
    "MetricSample",
    "MovementDirection",
    "ObjectDetector",
    "Profile",
    "ProfileRepository",
    "ResultsRepository",
    "RotationDirection",
    "VideoSource",
    "VideoSourceState",
    "VideoSourceStatus",
    "csv_rows",
    "experiment_to_document",
]
