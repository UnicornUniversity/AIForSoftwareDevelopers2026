"""Video source interface.

One abstraction covers the simulated video file and the live Tello camera, so
detectors, the Dry Run view and the tracking controller never need to know
where frames come from.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from ..domain import Frame

__all__ = ["VideoSource", "VideoSourceState", "VideoSourceStatus"]


class VideoSourceState(StrEnum):
    CLOSED = "closed"
    OPENING = "opening"
    READY = "ready"
    PAUSED = "paused"
    ENDED = "ended"
    ERROR = "error"


class VideoSourceStatus(StrEnum):
    """Coarse health of a source, for the UI badge."""

    OFFLINE = "offline"
    LIVE = "live"
    STALE = "stale"
    ENDED = "ended"
    ERROR = "error"


@runtime_checkable
class VideoSource(Protocol):
    """A pull-based frame source.

    ``read()`` is called from a worker thread at the consumer's pace; it must
    not block indefinitely. It returns ``None`` when no frame is available yet
    or the source has ended.
    """

    @property
    def source_id(self) -> str:
        """Stable identifier, unique per open source instance."""

    @property
    def state(self) -> VideoSourceState: ...

    @property
    def status(self) -> VideoSourceStatus: ...

    @property
    def description(self) -> str:
        """Human-readable description for the UI, e.g. a file name."""

    def open(self) -> None:
        """Prepare the source. Raises an application error on failure."""

    def close(self) -> None:
        """Release resources. Safe to call repeatedly."""

    def read(self) -> Frame | None:
        """Return the next frame, or ``None`` when unavailable/ended."""

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def seek(self, position_seconds: float) -> bool:
        """Seek if supported; returns False when the source cannot seek."""

    def set_looping(self, looping: bool) -> None: ...
