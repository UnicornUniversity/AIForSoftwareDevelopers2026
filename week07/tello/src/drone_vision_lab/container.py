"""Composition root.

Everything the UI needs is assembled here and handed over as one object, so no
widget ever constructs an adapter itself. Swapping the fake drone for the real
Tello adapter (phase 8) or the fake detectors for OpenCV/YOLO/VLM (phases 3-5)
changes this file only.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field

from .adapters.drone import TelloDroneAdapter
from .adapters.storage import JsonProfileRepository, JsonResultsRepository
from .adapters.video import VideoSourceFactory, make_video_source
from .adapters.vision import OpenCvTargetDetector, YoloDetector
from .adapters.vlm import OllamaVlmDetector
from .domain import DetectorKind
from .experiment import ExperimentSession
from .fakes import FakeDroneAdapter
from .interfaces import (
    Detector,
    DroneAdapter,
    ProfileRepository,
    ResultsRepository,
)
from .state import AppStateStore

__all__ = ["AppServices", "DetectorEvents", "build_default_services"]

_log = logging.getLogger(__name__)

_DRONE_MODE_ENV = "DRONE_VISION_LAB_DRONE"
_SIMULATED_ALIASES = {"", "simulated", "sim", "fake"}
_TELLO_ALIASES = {"tello", "hardware", "real"}

DetectorListener = Callable[[DetectorKind], None]


@dataclass(slots=True)
class DetectorEvents:
    """Broadcast detector-slot replacements to every view that reads them.

    ``AppServices.detectors`` is a plain dict, so installing a detector through
    a settings dialog or a profile load is invisible to the other tabs. A tab
    that reads the slot as a flight gate (the apple-recognition preset's
    Execute button needs a loaded YOLO model) would then keep a stale decision
    until an unrelated state change happened to refresh it, while the model is
    in fact installed.

    Publishers call :meth:`publish` after replacing a detector. Listeners only
    re-read the slot: refreshing a status label starts no source, loads no
    model and sends no command. Listeners run on the caller's thread, so the
    publishers must stay on the GUI thread.
    """

    _listeners: list[DetectorListener] = field(default_factory=list)

    def subscribe(self, listener: DetectorListener) -> Callable[[], None]:
        """Register a listener; returns a callable that removes it."""
        self._listeners.append(listener)

        def _unsubscribe() -> None:
            self.unsubscribe(listener)

        return _unsubscribe

    def unsubscribe(self, listener: DetectorListener) -> None:
        with contextlib.suppress(ValueError):
            self._listeners.remove(listener)

    def publish(self, kind: DetectorKind) -> None:
        """Tell every listener that ``kind`` now holds a different detector."""
        for listener in tuple(self._listeners):
            try:
                listener(kind)
            except Exception:  # noqa: BLE001 - one broken view must not stop the rest
                _log.exception("Detector-change listener %r failed", listener)


@dataclass(slots=True)
class AppServices:
    """Handles to every collaborator the application needs."""

    state: AppStateStore
    drone: DroneAdapter
    video_source_factory: VideoSourceFactory
    detectors: dict[DetectorKind, Detector]
    profiles: ProfileRepository
    results: ResultsRepository
    experiment: ExperimentSession
    drone_mode: str = "simulated"
    """``"simulated"`` or ``"tello"``. Comes from ``DRONE_VISION_LAB_DRONE``."""

    # Populated by later phases; kept here so the UI can show what is missing.
    notes: tuple[str, ...] = field(default_factory=tuple)

    detector_events: DetectorEvents = field(default_factory=DetectorEvents)
    """Tells every tab when a dialog or profile replaces a detector.

    The dict above has no notification of its own; without this a tab that
    gates on a detector (the apple preset) could stay disabled after the model
    was installed elsewhere.
    """


def build_default_services(*, drone_mode: str | None = None) -> AppServices:
    """Build the service graph.

    The default build is simulated: no socket is opened, no model is loaded and
    no command can reach hardware. The command-line ``--tello`` flag (passed here
    as ``drone_mode``) or ``DRONE_VISION_LAB_DRONE=tello`` selects the
    standard-Tello adapter instead; the flag wins when both are present, and the
    adapter still opens no socket until the operator presses Connect.

    All three detectors are real but only become usable after the operator
    calibrates or configures them; a missing OpenCV, Ultralytics install or
    Ollama service only disables that one detector.

    Profiles and experiment results are stored under :func:`app_data_dir`, so
    they survive a restart. Selecting a profile never starts a video source and
    never sends a command.
    """
    mode, mode_warning = _requested_drone_mode(drone_mode)
    hardware = mode == "tello"
    results = JsonResultsRepository()
    notes = [
        (
            "Hardware mode: commands go to a standard DJI Tello at 192.168.10.1. "
            "Connecting sends no takeoff command."
            if hardware
            else "Simulation only: no drone connection is active in this build."
        ),
        "Vision detectors are real but need calibration or a local model; "
        "the VLM is advisory and never controls the aircraft.",
    ]
    if hardware:
        notes.append(
            "Live Tello video is never recorded automatically; the camera source "
            "only decodes the stream for the comparison view."
        )
    if mode_warning:
        notes.append(mode_warning)
    # Gamepad input is intentionally not wired into this build. The mapping
    # module, its interface/fake and the pygame adapter remain on disk for a
    # future lesson; nothing here imports pygame or constructs an adapter.
    return AppServices(
        state=AppStateStore(),
        drone=TelloDroneAdapter() if hardware else FakeDroneAdapter(),
        video_source_factory=make_video_source,
        detectors={
            DetectorKind.OPENCV: OpenCvTargetDetector(),
            DetectorKind.YOLO: YoloDetector(),
            DetectorKind.VLM: OllamaVlmDetector(),
        },
        profiles=JsonProfileRepository(),
        results=results,
        experiment=ExperimentSession(results),
        drone_mode=mode,
        notes=tuple(notes),
    )


def _requested_drone_mode(override: str | None = None) -> tuple[str, str | None]:
    """Resolve the drone mode from the command line or the environment.

    An explicit command-line value takes precedence. Refuse to guess silently:
    an unknown value falls back to simulation and adds a visible note.
    """
    if override is not None:
        raw = override.strip().lower()
        if raw in _SIMULATED_ALIASES:
            return "simulated", None
        if raw in _TELLO_ALIASES:
            return "tello", None
        _log.warning(
            "Ignoring unknown command-line drone mode",
            extra={"context": {"drone_mode": raw}},
        )
        return "simulated", (
            f"Unknown command-line drone mode {override!r} was ignored; the "
            "simulated aircraft is in use."
        )
    raw = os.environ.get(_DRONE_MODE_ENV, "").strip().lower()
    if raw in _SIMULATED_ALIASES:
        return "simulated", None
    if raw in _TELLO_ALIASES:
        return "tello", None
    _log.warning(
        "Ignoring unknown drone mode",
        extra={"context": {_DRONE_MODE_ENV: raw}},
    )
    return "simulated", (
        f"Unknown {_DRONE_MODE_ENV} value {raw!r} was ignored; the simulated "
        "aircraft is in use."
    )
