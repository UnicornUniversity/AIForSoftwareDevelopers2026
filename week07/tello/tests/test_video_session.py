"""VideoSession: exclusive ownership, Tello streamon/streamoff, file sources.

Every collaborator is a double. The only commands the session may send are
``streamon`` and ``streamoff``; the tests assert nothing else reaches the drone.
"""

from __future__ import annotations

import time

from drone_vision_lab.domain import Frame
from drone_vision_lab.fakes import FakeDroneAdapter
from drone_vision_lab.interfaces.video import VideoSourceState, VideoSourceStatus
from drone_vision_lab.ui.video_session import VideoSession

OWNER = "object_feedback"


class _QuietSource:
    """A source whose ``read`` never produces a frame."""

    def __init__(self) -> None:
        self.opened = False
        self.closed = False
        self.looping = False
        self._state = VideoSourceState.CLOSED

    @property
    def source_id(self) -> str:
        return "test::quiet"

    @property
    def state(self) -> VideoSourceState:
        return self._state

    @property
    def status(self) -> VideoSourceStatus:
        return VideoSourceStatus.LIVE if self.opened else VideoSourceStatus.OFFLINE

    @property
    def description(self) -> str:
        return "Test source"

    def open(self) -> None:
        self.opened = True
        self._state = VideoSourceState.READY

    def close(self) -> None:
        self.closed = True
        self._state = VideoSourceState.CLOSED

    def read(self) -> Frame | None:
        return None

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def seek(self, position_seconds: float) -> bool:
        return False

    def set_looping(self, looping: bool) -> None:
        self.looping = looping


def _wait(qapp, predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _hardware(services):
    services.drone_mode = "tello"
    assert services.drone.connect().ok
    services.state.update(drone_connected=True)
    return services


def _session(services, source: _QuietSource | None = None, *, owner: str = OWNER):
    created = source or _QuietSource()
    session = VideoSession(
        services, owner=owner, source_factory=lambda _kind, _path: created
    )
    return session, created


def test_tello_start_is_refused_in_simulated_mode(qapp, services):
    session, source = _session(services)
    failures: list[str] = []
    session.failed.connect(lambda _title, message: failures.append(message))

    assert session.start("tello") is False
    assert failures and "--tello" in failures[0]
    assert session.active is False
    assert source.opened is False
    assert services.drone.commands == ()


def test_tello_start_is_refused_before_the_aircraft_is_connected(qapp, services):
    services.drone_mode = "tello"
    session, _ = _session(services)
    failures: list[str] = []
    session.failed.connect(lambda _title, message: failures.append(message))

    assert session.start("tello") is False
    assert failures and "Connect" in failures[0]
    assert services.drone.commands == ()


def test_start_is_refused_when_another_tab_owns_the_camera(qapp, services):
    _hardware(services)
    services.state.update(
        video_active=True, video_source_type="tello", video_owner="tello_flight"
    )
    session, source = _session(services)
    failures: list[str] = []
    session.failed.connect(lambda _title, message: failures.append(message))

    assert session.start("tello") is False
    assert failures and "Another tab" in failures[0]
    assert source.opened is False
    assert "streamon" not in services.drone.commands


def test_tello_start_claims_ownership_after_streamon(qapp, services):
    _hardware(services)
    session, source = _session(services)
    opened: list[str] = []
    session.opened.connect(lambda _source, kind: opened.append(kind))

    assert session.start("tello") is True
    assert _wait(qapp, lambda: session.active)

    snapshot = services.state.snapshot()
    assert source.opened is True
    assert services.drone.commands[-1] == "streamon"
    assert snapshot.video_active is True
    assert snapshot.video_source_type == "tello"
    assert snapshot.video_owner == OWNER
    assert opened == ["tello"]
    session.shutdown()


def test_stop_releases_ownership_and_sends_streamoff(qapp, services):
    _hardware(services)
    session, source = _session(services)
    session.start("tello")
    assert _wait(qapp, lambda: session.active)

    session.stop()

    snapshot = services.state.snapshot()
    assert session.active is False
    assert source.closed is True
    assert snapshot.video_active is False
    assert snapshot.video_owner is None
    assert _wait(qapp, lambda: "streamoff" in services.drone.commands)
    assert set(services.drone.commands) <= {"connect", "streamon", "streamoff"}


def test_stop_during_streamon_never_opens_the_camera(qapp, services):
    services.drone = FakeDroneAdapter(command_delay=0.1)
    _hardware(services)
    session, source = _session(services)

    assert session.start("tello") is True
    session.stop()

    assert _wait(qapp, lambda: not session.busy)
    assert _wait(qapp, lambda: "streamoff" in services.drone.commands)
    assert source.opened is False
    assert session.active is False
    assert services.state.snapshot().video_owner is None


def test_an_open_failure_sends_streamoff_and_releases(qapp, services):
    _hardware(services)
    failures: list[str] = []

    def _broken(_kind, _path):
        raise RuntimeError("UDP 11111 is already in use")

    session = VideoSession(services, owner=OWNER, source_factory=_broken)
    session.failed.connect(lambda _title, message: failures.append(message))

    assert session.start("tello") is True
    assert _wait(qapp, lambda: failures)
    assert "UDP 11111" in failures[0]
    assert session.active is False
    assert _wait(qapp, lambda: "streamoff" in services.drone.commands)
    assert services.state.snapshot().video_owner is None


def test_closed_is_emitted_exactly_once_per_session(qapp, services):
    _hardware(services)
    session, _ = _session(services)
    closed: list[bool] = []
    session.closed.connect(lambda: closed.append(True))
    session.start("tello")
    assert _wait(qapp, lambda: session.active)

    session.stop()
    session.stop()
    session.shutdown()

    assert closed == [True]


def test_shutdown_sends_only_camera_commands(qapp, services):
    _hardware(services)
    session, source = _session(services)
    session.start("tello")
    assert _wait(qapp, lambda: session.active)

    session.shutdown()

    assert source.closed is True
    assert set(services.drone.commands) <= {"connect", "streamon", "streamoff"}


def test_a_file_source_opens_without_any_drone_command(qapp, services):
    session, source = _session(services)
    opened: list[str] = []
    session.opened.connect(lambda _source, kind: opened.append(kind))

    assert session.start("file", "clip.mp4", looping=True) is True

    snapshot = services.state.snapshot()
    assert source.opened is True
    assert source.looping is True
    assert opened == ["file"]
    assert snapshot.video_source_type == "file"
    assert snapshot.video_owner == OWNER
    assert services.drone.commands == ()


def test_stopping_a_file_sends_no_streamoff(qapp, services):
    session, source = _session(services)
    assert session.start("file", "clip.mp4") is True

    session.stop()

    assert source.closed is True
    assert services.drone.commands == ()
    assert services.state.snapshot().video_owner is None


def test_a_file_source_does_not_need_hardware_mode(qapp, services):
    session, source = _session(services)

    assert services.drone_mode == "simulated"
    assert session.start("file", "clip.mp4") is True
    assert source.opened is True
    session.stop()
