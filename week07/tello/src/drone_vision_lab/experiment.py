"""Metric definitions and the live experiment session.

One place defines every metric this build records, what it means and — just as
importantly — when it is *not* applicable. Nothing here invents a value: a
metric that cannot be measured for an algorithm becomes ``None`` plus a note,
which the repositories store and the exports print as ``N/A``.

``ExperimentSession`` is the bridge between the vision pipeline and the results
repository: the UI starts it, the vision tab feeds it detection results, and
finishing it writes the summary samples.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass

from .domain import DetectionResult, DetectorKind
from .errors import ConfigurationError
from .interfaces.results import ExperimentContext, ExperimentRecord, MetricSample, ResultsRepository

__all__ = [
    "METRIC_DEFINITIONS",
    "ExperimentSession",
    "MetricDefinition",
    "MetricValue",
    "metric_definitions_document",
]


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """What a metric means, in the words an export reader needs."""

    key: str
    label: str
    unit: str
    description: str
    precision: int = 2


METRIC_DEFINITIONS: dict[str, MetricDefinition] = {
    definition.key: definition
    for definition in (
        MetricDefinition(
            "frames_analyzed",
            "Frames analyzed",
            "count",
            "Number of frames this algorithm was actually given. A dropped frame "
            "is not counted.",
            0,
        ),
        MetricDefinition(
            "detection_count",
            "Detections",
            "count",
            "Individual detections returned across all analyzed frames.",
            0,
        ),
        MetricDefinition(
            "detection_rate",
            "Detection rate",
            "fraction",
            "Frames with at least one detection divided by frames analyzed. "
            "Not applicable when no frame was analyzed.",
            3,
        ),
        MetricDefinition(
            "target_loss_events",
            "Target-loss events",
            "count",
            "Times a successful result with a target was followed by a successful "
            "result without one. Detector errors are not target loss.",
            0,
        ),
        MetricDefinition(
            "error_count",
            "Detector errors",
            "count",
            "Frames where the detector returned an error instead of a result.",
            0,
        ),
        MetricDefinition(
            "latency_mean_ms",
            "Mean latency",
            "ms",
            "Mean processing time over the results that reported one.",
            2,
        ),
        MetricDefinition(
            "latency_p95_ms",
            "P95 latency",
            "ms",
            "Nearest-rank 95th percentile processing time, so a slow tail is "
            "visible instead of hidden by the mean.",
            2,
        ),
        MetricDefinition(
            "fps",
            "Analysis rate",
            "Hz",
            "Frames analyzed divided by the elapsed time between the first and "
            "last analysis. For a periodic VLM poll this is not a video frame rate "
            "and is reported as not applicable.",
            2,
        ),
        MetricDefinition(
            "confidence_mean",
            "Mean confidence",
            "ratio",
            "Mean of the scores the algorithm itself reported. Not applicable when "
            "the algorithm reports no confidence score (OpenCV thresholding, VLM).",
            3,
        ),
        MetricDefinition(
            "tracking_stability",
            "Tracking stability",
            "ratio",
            "One minus the mean absolute normalized horizontal target error during "
            "a tracking session (1.0 = perfectly centred). Only defined for the "
            "algorithm that flew the tracking session.",
            3,
        ),
    )
}


def metric_definitions_document() -> dict[str, dict[str, str]]:
    """Definitions in the shape the JSON export embeds."""
    return {
        key: {
            "label": definition.label,
            "unit": definition.unit,
            "description": definition.description,
        }
        for key, definition in METRIC_DEFINITIONS.items()
    }


@dataclass(frozen=True, slots=True)
class MetricValue:
    """One metric value for one algorithm, applicable or explicitly not."""

    algorithm: str
    metric: str
    value: float | None
    unit: str = ""
    note: str = ""

    @property
    def applicable(self) -> bool:
        return self.value is not None

    @property
    def definition(self) -> MetricDefinition:
        return METRIC_DEFINITIONS[self.metric]

    def display_value(self) -> str:
        """Value for the table; ``N/A`` is a deliberate label, never a stand-in."""
        if self.value is None:
            return "N/A"
        precision = self.definition.precision
        if precision == 0:
            return f"{self.value:.0f}"
        return f"{self.value:.{precision}f}"

    def to_sample(self) -> MetricSample:
        return MetricSample(
            algorithm=self.algorithm,
            metric=self.metric,
            value=self.value,
            unit=self.unit,
            note=self.note,
        )


class _Accumulator:
    """Running totals for one algorithm during one experiment."""

    def __init__(self, kind: DetectorKind) -> None:
        self.kind = kind
        self.algorithm = kind.value
        self.frames = 0
        self.detections = 0
        self.frames_with_target = 0
        self.losses = 0
        self.errors = 0
        self.latencies: list[float] = []
        self.confidences: list[float] = []
        self.stability_errors: list[float] = []
        self.first_at: float | None = None
        self.last_at: float | None = None
        self._had_target = False

    def observe(self, result: DetectionResult, observed_at: float) -> None:
        self.frames += 1
        if self.first_at is None:
            self.first_at = observed_at
        self.last_at = observed_at
        if result.latency_ms is not None:
            self.latencies.append(float(result.latency_ms))
        if result.failed:
            self.errors += 1
            return
        if result.detections:
            self.frames_with_target += 1
            self.detections += len(result.detections)
            self.confidences.extend(
                detection.confidence
                for detection in result.detections
                if detection.confidence is not None
            )
            self._had_target = True
        else:
            if self._had_target:
                self.losses += 1
            self._had_target = False

    def observe_stability(self, error: float) -> None:
        self.stability_errors.append(abs(float(error)))

    # -- summarising ---------------------------------------------------------

    def values(self) -> list[MetricValue]:
        values = [
            self._value("frames_analyzed", float(self.frames)),
            self._value("detection_count", float(self.detections)),
            self._rate("detection_rate", self.frames_with_target, self.frames),
            self._value("target_loss_events", float(self.losses)),
            self._value("error_count", float(self.errors)),
            self._mean("latency_mean_ms", self.latencies),
            self._value("latency_p95_ms", _percentile(self.latencies, 0.95)),
        ]
        values.append(self._fps())
        values.append(self._mean("confidence_mean", self.confidences))
        values.append(self._stability())
        return [value for value in values if value is not None]

    def _value(self, metric: str, value: float | None, note: str = "") -> MetricValue:
        definition = METRIC_DEFINITIONS[metric]
        return MetricValue(self.algorithm, metric, value, definition.unit, note)

    def _rate(self, metric: str, numerator: int, denominator: int) -> MetricValue:
        if denominator == 0:
            return self._value(metric, None, "No frames were analyzed.")
        return self._value(metric, numerator / denominator)

    def _mean(self, metric: str, samples: list[float]) -> MetricValue:
        if not samples:
            if metric == "confidence_mean":
                reason = "This algorithm reports no confidence score."
            else:
                reason = "No result reported a processing time."
            return self._value(metric, None, reason)
        return self._value(metric, sum(samples) / len(samples))

    def _fps(self) -> MetricValue:
        if self.kind is DetectorKind.VLM:
            return self._value(
                "fps",
                None,
                "The VLM is polled periodically; its analysis rate is not a video frame rate.",
            )
        if self.first_at is None or self.last_at is None or self.frames < 2:
            return self._value("fps", None, "Not enough timed results to compute a rate.")
        elapsed = self.last_at - self.first_at
        if elapsed <= 0:
            return self._value("fps", None, "Elapsed time was not measurable.")
        return self._value("fps", self.frames / elapsed)

    def _stability(self) -> MetricValue:
        if not self.stability_errors:
            return self._value("tracking_stability", None, "No tracking session was recorded.")
        mean_error = sum(self.stability_errors) / len(self.stability_errors)
        return self._value("tracking_stability", max(0.0, min(1.0, 1.0 - mean_error)))


def _percentile(samples: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile; ``None`` for an empty sample set."""
    if not samples:
        return None
    ordered = sorted(samples)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


class ExperimentSession:
    """The experiment currently running, if any.

    Thread-safe: results arrive from the vision worker but the session is also
    read by the UI timer. Observing while no experiment is active is a no-op,
    so the vision pipeline never needs to branch on whether recording is on.
    """

    def __init__(self, results: ResultsRepository) -> None:
        self._results = results
        self._lock = threading.RLock()
        self._experiment_id: str | None = None
        self._context = ExperimentContext()
        self._accumulators: dict[DetectorKind, _Accumulator] = {}
        self._name = ""

    @property
    def experiment_id(self) -> str | None:
        return self._experiment_id

    @property
    def active(self) -> bool:
        return self._experiment_id is not None

    @property
    def name(self) -> str:
        return self._name

    @property
    def context(self) -> ExperimentContext:
        return self._context

    def start(self, name: str, context: ExperimentContext | None = None) -> str:
        with self._lock:
            if self._experiment_id is not None:
                raise ConfigurationError(
                    "An experiment is already running",
                    user_message="Finish the current experiment before starting another.",
                )
            clean_name = name.strip()
            if not clean_name:
                raise ConfigurationError(
                    "Experiment name must not be empty",
                    user_message="Enter a name for the experiment first.",
                )
            self._experiment_id = self._results.start_experiment(clean_name, context)
            self._context = context or ExperimentContext()
            self._name = clean_name
            self._accumulators = {}
            return self._experiment_id

    def observe(self, result: DetectionResult, *, observed_at: float) -> None:
        """Feed one detection result. Ignored when no experiment is running."""
        with self._lock:
            if self._experiment_id is None:
                return
            accumulator = self._accumulators.get(result.kind)
            if accumulator is None:
                accumulator = _Accumulator(result.kind)
                self._accumulators[result.kind] = accumulator
            accumulator.observe(result, observed_at)

    def observe_stability(self, kind: DetectorKind, error: float) -> None:
        """Feed one normalized horizontal tracking error (phase 10)."""
        with self._lock:
            if self._experiment_id is None:
                return
            accumulator = self._accumulators.setdefault(kind, _Accumulator(kind))
            accumulator.observe_stability(error)

    def summary(self) -> tuple[MetricValue, ...]:
        """Current live values, whether or not the experiment is active."""
        with self._lock:
            values: list[MetricValue] = []
            for kind in (DetectorKind.OPENCV, DetectorKind.YOLO, DetectorKind.VLM):
                accumulator = self._accumulators.get(kind)
                if accumulator is not None:
                    values.extend(accumulator.values())
            return tuple(values)

    def finish(self) -> ExperimentRecord | None:
        """Record the summary samples and close the experiment."""
        with self._lock:
            experiment_id = self._experiment_id
            if experiment_id is None:
                return None
            for value in self.summary():
                self._results.record_metric(
                    experiment_id,
                    value.algorithm,
                    value.metric,
                    value.value,
                    unit=value.unit,
                    note=value.note,
                )
            self._results.finish_experiment(experiment_id)
            self._experiment_id = None
            return self._results.get_experiment(experiment_id)
