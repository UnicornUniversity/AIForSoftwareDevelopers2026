"""Experiment Results panel: recording, live metrics, finishing and export."""

from __future__ import annotations

import csv
import time

import numpy as np
import pytest

from drone_vision_lab.adapters.storage import JsonResultsRepository
from drone_vision_lab.domain import (
    BoundingBox,
    Detection,
    DetectionResult,
    DetectorKind,
    Frame,
)
from drone_vision_lab.experiment import ExperimentSession
from drone_vision_lab.fakes import FakeDetector
from drone_vision_lab.ui.results_panel import ResultsPanel
from drone_vision_lab.ui.tabs.vision_lab import VisionLabTab

BOX = BoundingBox(0.2, 0.2, 0.2, 0.2)


def _result(
    kind: DetectorKind = DetectorKind.OPENCV,
    *,
    found: bool = True,
    latency_ms: float = 12.0,
    confidence: float | None = None,
) -> DetectionResult:
    detections = (
        (Detection(label="ball", box=BOX, confidence=confidence),) if found else ()
    )
    return DetectionResult(
        detector_name=kind.value,
        kind=kind,
        detections=detections,
        latency_ms=latency_ms,
    )


@pytest.fixture
def isolated(services, tmp_path):
    results = JsonResultsRepository(tmp_path / "results")
    services.results = results
    services.experiment = ExperimentSession(results)
    return services


@pytest.fixture
def panel(qapp, isolated):
    return ResultsPanel(isolated)


def _row_text(panel: ResultsPanel, row: int) -> list[str]:
    return [
        panel.table.item(row, column).text() for column in range(panel.table.columnCount())
    ]


def test_the_panel_starts_empty_and_says_so(panel):
    assert panel.table.isHidden() is True
    assert panel.empty_state.isHidden() is False
    assert panel.export_csv_button.isEnabled() is False
    assert panel.export_json_button.isEnabled() is False


def test_starting_an_experiment_enables_finishing(panel, isolated):
    panel.start_experiment("Demo")

    assert isolated.experiment.active is True
    assert panel.finish_button.isEnabled() is True
    assert panel.start_button.isEnabled() is False
    assert panel.name_edit.isEnabled() is False
    assert "Recording" in panel.status_text


def test_live_metrics_are_shown_while_recording(panel, isolated):
    panel.start_experiment("Demo")
    isolated.experiment.observe(_result(found=True), observed_at=0.0)
    isolated.experiment.observe(_result(found=False), observed_at=1.0)

    panel._refresh_live()  # noqa: SLF001 - deterministic timer tick

    rows = {
        _row_text(panel, row)[1]: _row_text(panel, row)
        for row in range(panel.table.rowCount())
    }
    assert rows["Frames analyzed"][2] == "2"
    assert rows["Detection rate"][2] == "0.500"
    assert rows["Mean latency"][2] == "12.00"


def test_a_metric_that_does_not_apply_is_shown_as_na_with_a_reason(panel, isolated):
    panel.start_experiment("Demo")
    isolated.experiment.observe(_result(DetectorKind.VLM), observed_at=0.0)
    isolated.experiment.observe(_result(DetectorKind.VLM), observed_at=2.0)

    panel._refresh_live()  # noqa: SLF001

    rows = {
        _row_text(panel, row)[1]: _row_text(panel, row)
        for row in range(panel.table.rowCount())
        if _row_text(panel, row)[0] == "vlm"
    }
    assert rows["Mean confidence"][2] == "N/A"
    assert "confidence" in rows["Mean confidence"][4]
    assert rows["Analysis rate"][2] == "N/A"
    assert "not a video frame rate" in rows["Analysis rate"][4]


def test_finishing_records_the_samples_and_enables_export(panel, isolated):
    panel.start_experiment("Demo")
    isolated.experiment.observe(_result(found=True), observed_at=0.0)

    record = panel.finish_experiment()

    assert record is not None
    assert record.samples
    assert isinstance(record.samples[0].algorithm, str)
    assert panel.export_csv_button.isEnabled() is True
    assert panel.export_json_button.isEnabled() is True
    assert "finished" in panel.status_text.lower()
    assert panel.table.rowCount() == len(record.samples)


def test_the_export_carries_the_context_that_was_running(panel, isolated):
    isolated.state.update(video_source_type="synthetic", active_profile_id="lecture")
    panel.start_experiment("Demo")
    isolated.experiment.observe(_result(), observed_at=0.0)
    record = panel.finish_experiment()

    assert record is not None
    assert record.source_type == "synthetic"
    assert record.profile_id == "lecture"
    assert "opencv" in record.algorithm_versions


def test_exporting_to_a_chosen_path_writes_the_file(panel, isolated, tmp_path):
    panel.start_experiment("Demo")
    isolated.experiment.observe(_result(), observed_at=0.0)
    panel.finish_experiment()

    csv_path = tmp_path / "experiment.csv"
    json_path = tmp_path / "experiment.json"
    assert panel.export_csv(str(csv_path)) == str(csv_path)
    assert panel.export_json(str(json_path)) == str(json_path)

    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["experiment"] == "Demo"
    assert rows[0]["experiment_id"].startswith("exp-")
    assert json_path.read_text(encoding="utf-8").strip().startswith("{")


def test_export_is_refused_before_finishing(panel, tmp_path):
    panel.start_experiment("Demo")

    assert panel.export_csv(str(tmp_path / "early.csv")) is None
    assert "Finish" in panel.status_text


def test_an_empty_experiment_finishes_without_inventing_measurements(panel):
    panel.start_experiment("Nothing measured")

    record = panel.finish_experiment()

    assert record is not None
    assert record.samples == ()
    assert panel.table.isHidden() is True
    assert panel.export_csv_button.isEnabled() is True


def test_shutdown_finishes_a_running_experiment(panel, isolated):
    panel.start_experiment("Interrupted")
    isolated.experiment.observe(_result(), observed_at=0.0)

    panel.shutdown()

    assert isolated.experiment.active is False
    assert panel.finished_record is not None


def test_meta_shows_the_source_and_profile_while_idle(panel, isolated):
    isolated.state.update(video_source_type="file", active_profile_id="lecture")

    panel.apply_state(isolated.state.snapshot())

    assert "Simulation video file" in panel.meta_text
    assert "lecture" in panel.meta_text


def test_the_vision_tab_feeds_the_running_experiment(qapp, isolated):
    detector = FakeDetector(kind=DetectorKind.OPENCV, detections=(
        Detection(label="ball", box=BOX, confidence=None),
    ))
    detector.load()
    isolated.detectors[DetectorKind.OPENCV] = detector
    tab = VisionLabTab(isolated)
    tab.set_mode(DetectorKind.OPENCV)
    isolated.experiment.start("Demo")

    image = np.zeros((120, 160, 3), dtype=np.uint8)
    frame = Frame(image=image, captured_at=time.monotonic(), source_id="synthetic", index=1)
    tab._on_frame(frame)  # noqa: SLF001 - drives the pipeline deterministically

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not isolated.experiment.summary():
        qapp.processEvents()
        time.sleep(0.01)

    values = {value.metric: value for value in isolated.experiment.summary()}
    assert values["frames_analyzed"].value == 1
    assert values["detection_count"].value == 1
