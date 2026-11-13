"""Standard DJI Tello protocol: settings, telemetry parsing and command syntax.

Only the documented standard-Tello SDK is modelled here. Nothing in this module
knows about UDP or sockets, which keeps the parsing and validation testable
without a network and keeps EDU-only verbs out of the code base.

References used when writing this module:

* Tello SDK command set (``command``, ``takeoff``, ``land``, ``streamon``,
  ``streamoff``, ``speed x``, ``<direction> x``, ``cw/ccw x``) — no mission
  pads, no ``mon``/``moff`` or other EDU functionality.
* Tello state packet format: ``key:value;`` pairs, sent to UDP port 8890.

A state packet is untrusted input: malformed fields are ignored, never guessed.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from ...domain import Telemetry

__all__ = [
    "MOVEMENT_DIRECTIONS",
    "TelloSettings",
    "build_move_command",
    "build_rotate_command",
    "is_acknowledgement",
    "is_error_reply",
    "normalize_command",
    "parse_state_packet",
]

MOVEMENT_DIRECTIONS = frozenset(
    {"up", "down", "left", "right", "forward", "back"}
)

_ROTATION_ALIASES = {
    "clockwise": "cw",
    "cw": "cw",
    "counter_clockwise": "ccw",
    "counterclockwise": "ccw",
    "ccw": "ccw",
}

# SDK limits for the commands this application sends.
_MIN_MOVE_CM = 20
_MAX_MOVE_CM = 500
_MIN_SPEED = 10
_MAX_SPEED = 100
_MIN_ROTATION_DEGREES = 1
_MAX_ROTATION_DEGREES = 360
_MAX_COMMAND_LENGTH = 64


@dataclass(frozen=True, slots=True)
class TelloSettings:
    """Connection and timing parameters for a standard Tello.

    Port numbers match the SDK documentation: commands are sent to 8889, state
    packets arrive on 8890 and video packets on 11111. The local ports are the
    ports this computer listens on; the command socket uses an ephemeral local
    port because the Tello replies to the sender's address.
    """

    host: str = "192.168.10.1"
    command_port: int = 8889
    state_port: int = 8890
    video_port: int = 11111
    local_state_port: int = 8890
    local_video_port: int = 11111
    response_timeout_s: float = 5.0
    state_timeout_s: float = 1.0
    min_command_interval_s: float = 0.1
    landing_confirm_timeout_s: float = 3.0
    video_stale_after_s: float = 2.0

    def __post_init__(self) -> None:
        if not self.host:
            raise ValueError("host must not be empty")
        for name in (
            "command_port",
            "state_port",
            "video_port",
            "local_state_port",
            "local_video_port",
        ):
            port = getattr(self, name)
            if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
                raise ValueError(f"{name} must be a UDP port number")
        for name in (
            "response_timeout_s",
            "state_timeout_s",
            "min_command_interval_s",
            "landing_confirm_timeout_s",
            "video_stale_after_s",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative number")


def is_acknowledgement(reply: str) -> bool:
    """True for the SDK's success reply. ``ok`` proves acceptance, not state."""
    return reply.strip().lower() == "ok"


def is_error_reply(reply: str) -> bool:
    """True for ``error ...``; the aircraft refused the command."""
    return reply.strip().lower().startswith("error")


def normalize_command(command: str) -> str:
    """Validate a raw SDK command before it reaches the wire.

    A newline in a command would inject a second command, so it is rejected
    rather than stripped. Empty and over-long strings are programming errors,
    not things to send and see what happens.
    """
    if not isinstance(command, str):
        raise ValueError("command must be a string")
    cleaned = command.strip()
    if not cleaned:
        raise ValueError("command must not be empty")
    if len(cleaned) > _MAX_COMMAND_LENGTH:
        raise ValueError(f"command is longer than {_MAX_COMMAND_LENGTH} characters")
    if any(character in cleaned for character in "\r\n\x00"):
        raise ValueError("command must not contain line breaks or NUL characters")
    return cleaned


def build_move_command(direction: str, distance_cm: int) -> str:
    """Build ``<direction> <distance>``, validated against the SDK limits."""
    if direction not in MOVEMENT_DIRECTIONS:
        raise ValueError(
            f"Unknown movement direction {direction!r}; expected one of "
            f"{sorted(MOVEMENT_DIRECTIONS)}"
        )
    if isinstance(distance_cm, bool) or not isinstance(distance_cm, int):
        raise ValueError("distance_cm must be an integer")
    if not _MIN_MOVE_CM <= distance_cm <= _MAX_MOVE_CM:
        raise ValueError(
            f"distance_cm must be between {_MIN_MOVE_CM} and {_MAX_MOVE_CM}"
        )
    return f"{direction} {distance_cm}"


def build_rotate_command(direction: str, degrees: int) -> str:
    """Build ``cw <degrees>`` or ``ccw <degrees>``."""
    verb = _ROTATION_ALIASES.get(direction)
    if verb is None:
        raise ValueError(
            f"Unknown rotation direction {direction!r}; expected 'clockwise' or "
            "'counter_clockwise'"
        )
    if isinstance(degrees, bool) or not isinstance(degrees, int):
        raise ValueError("degrees must be an integer")
    if not _MIN_ROTATION_DEGREES <= degrees <= _MAX_ROTATION_DEGREES:
        raise ValueError(
            f"degrees must be between {_MIN_ROTATION_DEGREES} and "
            f"{_MAX_ROTATION_DEGREES}"
        )
    return f"{verb} {degrees}"


def parse_state_packet(
    payload: str | bytes,
    *,
    received_at: float | None = None,
) -> Telemetry | None:
    """Parse one ``key:value;`` state packet.

    Returns ``None`` when the payload is not a state packet at all (no
    ``key:value`` pair). Individual unknown or malformed fields are dropped:
    the returned telemetry keeps ``None`` for anything the aircraft did not
    report in a usable form.
    """
    if isinstance(payload, bytes):
        try:
            text = payload.decode("ascii", errors="ignore")
        except Exception:  # pragma: no cover - decoding never raises with "ignore"
            return None
    else:
        text = payload

    fields: dict[str, str] = {}
    for part in text.split(";"):
        if ":" not in part:
            continue
        key, _, value = part.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key:
            fields[key] = value

    if not fields:
        return None

    # ``h`` is height in cm, ``bat`` battery %, ``time`` flight time in s.
    # The state packet reports two temperatures; take the high one as the
    # closer-to-motor reading rather than averaging readings with no meaning.
    return Telemetry(
        battery_percent=_int_field(fields, "bat", 0, 100),
        height_cm=_int_field(fields, "h", 0, None),
        flight_time_s=_int_field(fields, "time", 0, None),
        temperature_c=_float_field(fields.get("temph") or fields.get("templ")),
        received_at=time.monotonic() if received_at is None else received_at,
    )


def _int_field(
    fields: dict[str, str],
    key: str,
    minimum: int,
    maximum: int | None,
) -> int | None:
    raw = fields.get(key)
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value < minimum or (maximum is not None and value > maximum):
        return None
    return value


def _float_field(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return value
