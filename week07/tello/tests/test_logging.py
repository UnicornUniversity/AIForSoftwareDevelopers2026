"""Structured logging configuration."""

from __future__ import annotations

import logging

import drone_vision_lab.logging_setup as logging_setup


class _HandlerScope:
    """Removes handlers installed by the code under test."""

    def __init__(self) -> None:
        self._root = logging.getLogger()
        self._before = list(self._root.handlers)

    def __enter__(self) -> logging.Logger:
        return self._root

    def __exit__(self, *_exc) -> None:
        for handler in list(self._root.handlers):
            if handler not in self._before:
                self._root.removeHandler(handler)
                handler.close()


def test_configure_logging_writes_structured_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_setup, "_CONFIGURED", False)
    with _HandlerScope():
        path = logging_setup.configure_logging(logging.INFO, log_dir=tmp_path)
        logging.getLogger("drone_vision_lab.test").info(
            "frame processed", extra={"context": {"detector": "yolo", "latency_ms": 12}}
        )
        for handler in logging.getLogger().handlers:
            handler.flush()

        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "frame processed" in content
        assert "detector='yolo'" in content
        assert "latency_ms=12" in content


def test_configure_logging_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_setup, "_CONFIGURED", False)
    with _HandlerScope() as root:
        logging_setup.configure_logging(logging.INFO, log_dir=tmp_path)
        added = len(root.handlers)
        logging_setup.configure_logging(logging.DEBUG, log_dir=tmp_path)
        assert len(root.handlers) == added


def test_log_file_path_is_under_configured_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DRONE_VISION_LAB_HOME", str(tmp_path))
    assert logging_setup.get_log_file().parent == tmp_path / "logs"


def test_the_log_level_can_be_selected_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_setup, "_CONFIGURED", False)
    monkeypatch.setenv("DRONE_VISION_LAB_LOG_LEVEL", "DEBUG")
    with _HandlerScope() as root:
        logging_setup.configure_logging(log_dir=tmp_path)
        assert root.level == logging.DEBUG


def test_an_unreadable_log_level_falls_back_to_info(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_setup, "_CONFIGURED", False)
    monkeypatch.setenv("DRONE_VISION_LAB_LOG_LEVEL", "not-a-level")
    with _HandlerScope() as root:
        logging_setup.configure_logging(log_dir=tmp_path)
        assert root.level == logging.INFO
