"""Application bootstrap.

Creates the Qt application, configures logging, builds the service graph and
shows the main window. Nothing here opens a socket, loads a model or touches a
camera: the defaults come from :func:`build_default_services`.
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .config import APP_NAME, APP_ORG
from .container import build_default_services
from .logging_setup import configure_logging
from .ui.main_window import MainWindow

__all__ = [
    "AppArguments",
    "create_application",
    "install_exception_hook",
    "main",
    "parse_arguments",
    "parse_drone_mode",
]

_log = logging.getLogger(__name__)

_LOG_LEVEL_NAMES = ("DEBUG", "INFO", "WARNING", "ERROR")
_LOG_LEVELS: dict[str, int] = {name: getattr(logging, name) for name in _LOG_LEVEL_NAMES}


@dataclass(frozen=True, slots=True)
class AppArguments:
    """Options taken off the command line before Qt sees the rest."""

    drone_mode: str | None = None
    log_level: int | None = None
    qt_arguments: tuple[str, ...] = ()


def parse_arguments(argv: Sequence[str]) -> AppArguments:
    """Take the application's own flags out of the command line.

    The remaining arguments are handed to Qt unchanged. An explicit flag wins over
    the environment; with no flag, ``DRONE_VISION_LAB_DRONE`` and
    ``DRONE_VISION_LAB_LOG_LEVEL`` still decide.
    """
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Drone Vision Lab — choose the aircraft backend and log detail.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--tello",
        dest="drone_mode",
        action="store_const",
        const="tello",
        help="Use the real DJI Tello adapter (hardware mode).",
    )
    mode.add_argument(
        "--simulated",
        dest="drone_mode",
        action="store_const",
        const="simulated",
        help="Use the simulated aircraft (the default).",
    )
    detail = parser.add_mutually_exclusive_group()
    detail.add_argument(
        "--debug",
        action="store_true",
        help=(
            "Write DEBUG-level records to the console and the log file. Wins over "
            "DRONE_VISION_LAB_LOG_LEVEL; the log file grows quickly."
        ),
    )
    detail.add_argument(
        "--log-level",
        dest="log_level",
        metavar="LEVEL",
        type=str.upper,
        choices=_LOG_LEVEL_NAMES,
        help=(
            "Log level for the console and the log file: "
            + ", ".join(_LOG_LEVEL_NAMES)
            + ". Wins over DRONE_VISION_LAB_LOG_LEVEL."
        ),
    )
    namespace, remaining = parser.parse_known_args(list(argv))

    level: int | None = None
    if namespace.debug:
        level = logging.DEBUG
    elif namespace.log_level is not None:
        level = _LOG_LEVELS[namespace.log_level]
    return AppArguments(
        drone_mode=namespace.drone_mode,
        log_level=level,
        qt_arguments=tuple(remaining),
    )


def parse_drone_mode(argv: Sequence[str]) -> tuple[str | None, list[str]]:
    """Return the requested mode (``None`` with no flag) and Qt's arguments."""
    arguments = parse_arguments(argv)
    return arguments.drone_mode, list(arguments.qt_arguments)


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setApplicationVersion(__version__)
    return app


def install_exception_hook() -> None:
    """Log uncaught exceptions and surface them instead of dying silently."""

    def _hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        _log.critical(
            "Uncaught exception",
            exc_info=(exc_type, exc, tb),
            extra={"context": {"exception": exc_type.__name__}},
        )
        detail = "".join(traceback.format_exception_only(exc_type, exc)).strip()
        QMessageBox.critical(
            None,
            "Unexpected error",
            f"{detail}\n\nDetails were written to the log file.",
        )

    sys.excepthook = _hook


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv if argv is None else argv)
    program = raw[0] if raw else APP_NAME
    arguments = parse_arguments(raw[1:])

    log_file = configure_logging(arguments.log_level)
    _log.info(
        "Starting %s",
        APP_NAME,
        extra={
            "context": {
                "log_file": str(log_file),
                "drone_mode": arguments.drone_mode or "from environment",
                "log_level": logging.getLevelName(logging.getLogger().level),
                "log_level_source": (
                    "command line"
                    if arguments.log_level is not None
                    else "environment or default"
                ),
            }
        },
    )

    app = create_application([program, *arguments.qt_arguments])
    install_exception_hook()
    services = build_default_services(drone_mode=arguments.drone_mode)

    window = MainWindow(services)
    window.show()
    return app.exec()
