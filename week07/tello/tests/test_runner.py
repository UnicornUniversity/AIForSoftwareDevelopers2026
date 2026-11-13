"""CallableRunner: one job at a time, and a clean teardown while a job runs."""

from __future__ import annotations

import gc
import sys
import threading

from PySide6.QtCore import QThreadPool

from drone_vision_lab.workers.runner import CallableRunner


def test_a_job_finishing_after_its_runner_was_destroyed_does_not_raise(
    qapp, monkeypatch
):
    """Closing a dialog while its worker runs must not become an app error.

    The dialog owns the runner. Destroying the dialog destroys the runner, but
    the thread-pool job is still running and will emit when it finishes. That
    emission has nowhere to go and must be dropped quietly.
    """
    uncaught: list[BaseException] = []
    monkeypatch.setattr(sys, "excepthook", lambda _t, exc, _tb: uncaught.append(exc))

    started = threading.Event()
    release = threading.Event()
    work_finished = threading.Event()

    def work() -> int:
        started.set()
        release.wait(5.0)
        work_finished.set()
        return 7

    runner = CallableRunner()
    received: list[object] = []
    runner.finished.connect(received.append)
    assert runner.submit(work) is True
    assert started.wait(5.0)

    del runner
    gc.collect()

    release.set()
    assert work_finished.wait(5.0)
    assert QThreadPool.globalInstance().waitForDone(5000)
    qapp.processEvents()

    assert received == []
    assert uncaught == []
