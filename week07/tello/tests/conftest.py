"""Shared pytest fixtures.

The whole suite must run with no drone, no GPU, no Ollama service, no network
and no visible display, so Qt is forced onto the offscreen platform plugin and
all application state is redirected to a temporary directory.

Hardware, model and Ollama smoke tests are marked and excluded by default; run
them explicitly with ``-m hardware``, ``-m model`` or ``-m ollama``.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "DRONE_VISION_LAB_HOME", str(Path(tempfile.mkdtemp(prefix="dvl-test-home-")) / "app"))
os.environ.setdefault("DRONE_VISION_LAB_LOG_LEVEL", "WARNING")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session; Qt forbids more than one."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def dispose_widgets(qapp):
    """Delete top-level widgets while QApplication is still alive.

    Leaving unparented widgets to Python's interpreter shutdown lets Qt destroy
    them after the application object is gone, which crashes the offscreen
    platform plugin on Windows. Deleting them here keeps the suite's exit code
    meaningful.
    """
    yield
    for widget in qapp.topLevelWidgets():
        widget.deleteLater()
    qapp.processEvents()


@pytest.fixture
def services():
    from drone_vision_lab.container import build_default_services

    return build_default_services()


@pytest.fixture
def window(qapp, services) -> Iterator[object]:
    from drone_vision_lab.ui.main_window import MainWindow

    win = MainWindow(services)
    yield win
    win.close()


@pytest.fixture
def sample_video(tmp_path) -> Path:
    """A short AVI generated at test time, so no video asset is bundled."""
    cv2 = pytest.importorskip("cv2")
    numpy = pytest.importorskip("numpy")

    path = tmp_path / "sample.avi"
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (64, 48)
    )
    if not writer.isOpened():
        pytest.skip("OpenCV cannot write MJPG video in this environment")
    for index in range(10):
        writer.write(numpy.full((48, 64, 3), index * 20, dtype=numpy.uint8))
    writer.release()
    return path
