"""Application identity, default locations and conservative safety defaults.

Paths default to per-user locations on Windows and can be redirected with the
``DRONE_VISION_LAB_HOME`` environment variable, which is what tests and the
classroom machines use to keep state out of the student's profile.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "APP_NAME",
    "APP_ORG",
    "CONSERVATIVE_LIMITS",
    "DEFAULT_OLLAMA_BASE_URL",
    "SafetyLimits",
    "app_data_dir",
    "logs_dir",
    "profiles_dir",
    "results_dir",
    "videos_dir",
]

APP_NAME = "Drone Vision Lab"
APP_ORG = "Unicorn University"

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


@dataclass(frozen=True, slots=True)
class SafetyLimits:
    """Conservative classroom defaults. Every value is configurable in a profile.

    The takeoff floor is an operator setting and may be lower than the in-flight
    minimum; programs that move still refuse to move below that minimum.
    """

    min_battery_percent_for_takeoff: int = 10
    """Operator-set takeoff floor. It is below min_battery_percent_in_flight,
    so a program that moves will refuse its first movement below 20 %."""
    min_battery_percent_in_flight: int = 20
    max_battery_percent_for_mission: int = 100
    max_altitude_cm: int = 150
    max_segment_distance_cm: int = 100
    max_speed_cm_s: int = 50
    max_mission_duration_s: int = 120
    max_tracking_session_s: int = 60
    command_timeout_s: float = 5.0
    min_command_interval_s: float = 0.1
    telemetry_max_age_s: float = 1.0
    """A snapshot older than this is stale and cannot satisfy a safety gate.

    A hardware adapter reports its own limit and the tabs prefer it
    (:attr:`TelloDroneAdapter.telemetry_max_age_s`, which follows the Tello's
    state-packet timeout). This default is the simulated-aircraft equivalent;
    it is the same value so the same gate cannot mean two different ages
    depending on which aircraft is selected.
    """
    takeoff_settle_s: float = 5.0
    """Wait after the takeoff acknowledgement before the climb or first move."""


CONSERVATIVE_LIMITS = SafetyLimits()


def app_data_dir() -> Path:
    """Root directory for logs, profiles and results."""
    override = os.environ.get("DRONE_VISION_LAB_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "DroneVisionLab"
    return Path.home() / ".local" / "share" / "drone-vision-lab"


def logs_dir() -> Path:
    return app_data_dir() / "logs"


def profiles_dir() -> Path:
    return app_data_dir() / "profiles"


def results_dir() -> Path:
    return app_data_dir() / "results"


def videos_dir() -> Path:
    """Default folder for the operator's video files.

    This is the application's own ``video`` subfolder (gitignored), not the home
    directory, so a classroom machine keeps demo clips with the app. When the
    application is packaged, the folder sits next to the executable.
    """
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        # <project>/src/drone_vision_lab/config.py -> <project>
        base = Path(__file__).resolve().parents[2]
    return base / "video"
