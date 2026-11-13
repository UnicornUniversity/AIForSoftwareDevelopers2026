"""Standard DJI Tello hardware adapters.

Only the standard Tello SDK is implemented. The composition root builds these
objects when hardware mode is requested; the default build never opens a socket.
"""

from .command_channel import CommandChannel
from .diagnostics import (
    DiagnosticCheck,
    format_diagnostic_report,
    is_tello_address,
    run_tello_diagnostics,
)
from .state_receiver import TelloStateReceiver
from .tello_drone import TelloDroneAdapter
from .tello_protocol import (
    MOVEMENT_DIRECTIONS,
    TelloSettings,
    build_move_command,
    build_rotate_command,
    parse_state_packet,
)
from .video_stream import TelloVideoReceiver

__all__ = [
    "MOVEMENT_DIRECTIONS",
    "CommandChannel",
    "DiagnosticCheck",
    "TelloDroneAdapter",
    "TelloSettings",
    "TelloStateReceiver",
    "TelloVideoReceiver",
    "build_move_command",
    "build_rotate_command",
    "format_diagnostic_report",
    "is_tello_address",
    "parse_state_packet",
    "run_tello_diagnostics",
]
