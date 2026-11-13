"""Command-line selection: our flags are removed before Qt sees them."""

from __future__ import annotations

import logging

import pytest

from drone_vision_lab.app import parse_arguments, parse_drone_mode


def test_tello_flag_selects_hardware_and_is_removed_before_qt():
    mode, remaining = parse_drone_mode(["--tello", "-platform", "offscreen"])

    assert mode == "tello"
    assert remaining == ["-platform", "offscreen"]


def test_simulated_flag_can_override_the_environment():
    mode, remaining = parse_drone_mode(["--simulated"])

    assert mode == "simulated"
    assert remaining == []


def test_without_a_flag_the_environment_still_decides():
    mode, remaining = parse_drone_mode([])

    assert mode is None
    assert remaining == []


def test_the_two_mode_flags_are_mutually_exclusive():
    with pytest.raises(SystemExit) as caught:
        parse_drone_mode(["--tello", "--simulated"])

    assert caught.value.code == 2


def test_the_debug_flag_selects_debug_logging_and_is_removed_before_qt():
    arguments = parse_arguments(["--debug", "--tello", "-platform", "offscreen"])

    assert arguments.log_level == logging.DEBUG
    assert arguments.drone_mode == "tello"
    assert arguments.qt_arguments == ("-platform", "offscreen")


def test_the_log_level_flag_selects_a_named_level():
    arguments = parse_arguments(["--log-level", "warning"])

    assert arguments.log_level == logging.WARNING
    assert arguments.qt_arguments == ()


def test_without_a_detail_flag_the_environment_still_decides():
    # None means configure_logging() falls back to DRONE_VISION_LAB_LOG_LEVEL.
    assert parse_arguments([]).log_level is None


def test_an_unknown_log_level_is_refused():
    with pytest.raises(SystemExit) as caught:
        parse_arguments(["--log-level", "verbose"])

    assert caught.value.code == 2


def test_debug_and_log_level_cannot_be_combined():
    with pytest.raises(SystemExit) as caught:
        parse_arguments(["--debug", "--log-level", "INFO"])

    assert caught.value.code == 2
