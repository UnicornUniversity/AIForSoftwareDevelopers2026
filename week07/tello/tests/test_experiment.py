"""Experiment session and metric calculations.

Every number here is computed from results the test constructs, so the
arithmetic is checked directly instead of trusted.
"""

from __future__ import annotations

import pytest

from drone_vision_lab.domain import BoundingBox, Detection, DetectionResult, DetectorKind
from drone_vision_lab.errors import ConfigurationError
from drone_vision_lab.experiment import ExperimentSession, MetricValue
from drone_vision_lab.fakes import InMemoryResultsRepository
from drone_vision_lab.interfaces import ExperimentContext

BOX = BoundingBox(0.1, 0.1, 0.2, 0.2)


def _result(
    kind: DetectorKind = DetectorKind.OPENCV,
    *,
    found: bool = True,
    latency_ms: float | None = 10.0,
    confidence: float | None = None,
    error: str | None = None,
) -> DetectionResult:
    detections = (
        (Detection(label="ball", box=BOX, confidence=confidence),) if found else ()
    )
    return DetectionResult(
        detector_name=kind.value,
        kind=kind,
        detections=detections,
        latency_ms=latency_ms,
        error=error,
    )


def _session() -> ExperimentSession:
    return ExperimentSession(InMemoryResultsRepository())


def _values(session: ExperimentSession, algorithm: str = "opencv") -> dict[str, MetricValue]:
    return {
        value.metric: value
        for value in session.summary()
        if value.algorithm == algorithm
    }


def test_counts_rate_and_latency_are_computed_from_observations():
    session = _session()
    session.start("Demo")
    for index, found in enumerate([True, True, False, True]):
        session.observe(
            _result(found=found, latency_ms=10.0 * (index + 1)),
            observed_at=float(index),
        )

    values = _values(session)

    assert values["frames_analyzed"].value == 4
    assert values["detection_count"].value == 3
    assert values["detection_rate"].value == pytest.approx(0.75)
    assert values["latency_mean_ms"].value == pytest.approx(25.0)
    assert values["fps"].value == pytest.approx(4 / 3)


def test_target_loss_counts_only_a_found_to_not_found_transition():
    session = _session()
    session.start("Demo")
    for index, found in enumerate([True, True, False, True, False]):
        session.observe(_result(found=found), observed_at=float(index))

    assert _values(session)["target_loss_events"].value == 2


def test_a_detector_error_is_not_counted_as_target_loss():
    session = _session()
    session.start("Demo")
    session.observe(_result(found=True), observed_at=0.0)
    session.observe(_result(error="inference failed", found=True), observed_at=1.0)
    session.observe(_result(found=False), observed_at=2.0)

    values = _values(session)

    assert values["error_count"].value == 1
    assert values["target_loss_events"].value == 1
    assert values["frames_analyzed"].value == 3
    assert values["detection_count"].value == 1


def test_p95_latency_uses_nearest_rank():
    session = _session()
    session.start("Demo")
    for index in range(20):
        session.observe(_result(latency_ms=float(index + 1)), observed_at=float(index))

    values = _values(session)

    assert values["latency_mean_ms"].value == pytest.approx(10.5)
    assert values["latency_p95_ms"].value == pytest.approx(19.0)


def test_the_vlm_analysis_rate_is_reported_as_not_applicable():
    session = _session()
    session.start("Demo")
    session.observe(_result(DetectorKind.VLM, latency_ms=800.0), observed_at=0.0)
    session.observe(_result(DetectorKind.VLM, latency_ms=900.0), observed_at=2.0)

    fps = _values(session, "vlm")["fps"]

    assert fps.value is None
    assert "not a video frame rate" in fps.note


def test_open_cv_reports_no_confidence_and_says_so():
    session = _session()
    session.start("Demo")
    session.observe(_result(found=True), observed_at=0.0)

    confidence = _values(session)["confidence_mean"]

    assert confidence.value is None
    assert "no confidence" in confidence.note
    assert confidence.display_value() == "N/A"


def test_reported_confidences_are_averaged():
    session = _session()
    session.start("Demo")
    session.observe(
        _result(DetectorKind.YOLO, confidence=0.5), observed_at=0.0
    )
    session.observe(
        _result(DetectorKind.YOLO, confidence=0.7), observed_at=0.5
    )

    assert _values(session, "yolo")["confidence_mean"].value == pytest.approx(0.6)


def test_tracking_stability_is_defined_only_with_tracking_samples():
    session = _session()
    session.start("Demo")
    session.observe(_result(found=True), observed_at=0.0)
    assert _values(session)["tracking_stability"].value is None

    session.observe_stability(DetectorKind.OPENCV, 0.1)
    session.observe_stability(DetectorKind.OPENCV, -0.3)

    assert _values(session)["tracking_stability"].value == pytest.approx(0.8)


def test_observing_without_a_running_experiment_does_nothing():
    session = _session()
    session.observe(_result(), observed_at=0.0)

    assert session.summary() == ()
    assert session.finish() is None


def test_an_empty_experiment_records_no_invented_samples():
    session = _session()
    experiment_id = session.start("Empty")
    record = session.finish()

    assert record is not None
    assert record.experiment_id == experiment_id
    assert record.samples == ()


def test_finishing_writes_the_summary_and_closes_the_experiment():
    session = _session()
    session.start("Demo")
    session.observe(_result(found=True), observed_at=0.0)
    session.observe(_result(found=False), observed_at=1.0)

    record = session.finish()

    assert record is not None
    assert record.open is False
    assert session.active is False
    samples = {sample.metric: sample for sample in record.samples}
    assert samples["frames_analyzed"].value == 2
    assert samples["detection_rate"].value == pytest.approx(0.5)


def test_the_experiment_context_is_recorded():
    session = _session()
    context = ExperimentContext(
        source_type="file",
        source_description="Simulation video file",
        profile_id="lecture",
        algorithm_versions={"opencv": "OpenCV colour threshold"},
    )
    session.start("Demo", context)
    record = session.finish()

    assert record is not None
    assert record.source_type == "file"
    assert record.profile_id == "lecture"
    assert record.algorithm_versions == {"opencv": "OpenCV colour threshold"}


def test_a_second_experiment_cannot_start_while_one_runs():
    session = _session()
    session.start("First")

    with pytest.raises(ConfigurationError):
        session.start("Second")


def test_an_experiment_needs_a_name():
    session = _session()
    with pytest.raises(ConfigurationError):
        session.start("   ")
