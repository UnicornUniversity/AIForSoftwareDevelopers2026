"""Default locations: the video folder belongs to the application, not the user."""

from __future__ import annotations

from pathlib import Path

from drone_vision_lab.config import CONSERVATIVE_LIMITS, videos_dir


def test_the_video_folder_is_the_applications_own_subfolder():
    project_root = Path(__file__).resolve().parents[1]

    assert videos_dir() == project_root / "video"


def test_the_simulated_telemetry_age_matches_the_tello_state_timeout():
    """One gate, one number: the same limit must not differ by aircraft.

    The Tello adapter reports its own limit (derived from ``state_timeout_s``)
    and the tabs prefer it, so this default only applies to the simulated
    aircraft. If the two drift apart, the identical staleness gate accepts a
    different age depending on which build is running.
    """
    from drone_vision_lab.adapters.drone.tello_protocol import TelloSettings

    assert CONSERVATIVE_LIMITS.telemetry_max_age_s == TelloSettings().state_timeout_s
