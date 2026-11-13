"""Top-level tab widgets for the main window."""

from .drone_control import DroneControlTab
from .missions import MissionsTab
from .object_feedback import ObjectFeedbackTab
from .preset_missions import PresetMissionsTab
from .tello_flight import TelloFlightTab
from .vision_lab import VisionLabTab

__all__ = [
    "DroneControlTab",
    "MissionsTab",
    "ObjectFeedbackTab",
    "PresetMissionsTab",
    "TelloFlightTab",
    "VisionLabTab",
]
