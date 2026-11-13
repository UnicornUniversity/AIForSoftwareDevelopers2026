"""Experiment results contract.

Metrics are recorded as explicit ``(algorithm, metric, value)`` samples so that
"not applicable" stays distinguishable from "zero": a sample whose ``value`` is
``None`` must carry a ``note`` explaining why nothing was measured. The
repository never stores image or video data.

Every export carries the experiment name, both timestamps, the source type, the
profile it ran under and the algorithm/model versions, because a metric without
that context cannot be reproduced.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = [
    "EXPERIMENT_SCHEMA_VERSION",
    "ExperimentContext",
    "ExperimentRecord",
    "MetricSample",
    "ResultsRepository",
    "experiment_to_document",
    "csv_rows",
]

EXPERIMENT_SCHEMA_VERSION = 1

#: ``value`` and ``note`` columns are shared by every export format.
_CSV_COLUMNS = (
    "experiment",
    "experiment_id",
    "started_at",
    "finished_at",
    "source_type",
    "source_description",
    "profile_id",
    "algorithm",
    "algorithm_version",
    "metric",
    "value",
    "unit",
    "note",
)


@dataclass(frozen=True, slots=True)
class ExperimentContext:
    """What was running when the experiment started.

    Recorded once, at the start, so the export describes the setup rather than
    whatever happened to be selected when the file was written.
    """

    source_type: str = ""
    source_description: str = ""
    profile_id: str | None = None
    algorithm_versions: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MetricSample:
    """One recorded measurement.

    ``value is None`` means the metric was not applicable and ``note`` says why.
    Callers must never substitute a placeholder number.
    """

    algorithm: str
    metric: str
    value: float | None
    unit: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if not self.algorithm:
            raise ValueError("MetricSample.algorithm must not be empty")
        if not self.metric:
            raise ValueError("MetricSample.metric must not be empty")
        if self.value is None and not self.note:
            raise ValueError("A not-applicable metric needs a note explaining why")


@dataclass(frozen=True, slots=True)
class ExperimentRecord:
    """A complete experiment, ready to display or export."""

    experiment_id: str
    name: str
    source_type: str
    source_description: str
    profile_id: str | None
    algorithm_versions: Mapping[str, str]
    started_at: str
    finished_at: str | None
    samples: tuple[MetricSample, ...]
    schema_version: int = EXPERIMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.experiment_id:
            raise ValueError("ExperimentRecord.experiment_id must not be empty")
        if not self.name:
            raise ValueError("ExperimentRecord.name must not be empty")

    @property
    def open(self) -> bool:
        return self.finished_at is None


def experiment_to_document(
    record: ExperimentRecord,
    *,
    metric_definitions: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, object]:
    """The JSON export document.

    Samples stay grouped per algorithm, and each metric used gets its definition
    so the file explains itself without the application.
    """
    grouped: dict[str, list[dict[str, object]]] = {}
    for sample in record.samples:
        grouped.setdefault(sample.algorithm, []).append(
            {
                "metric": sample.metric,
                "value": sample.value,
                "unit": sample.unit,
                "note": sample.note,
            }
        )
    document: dict[str, object] = {
        "schema_version": record.schema_version,
        "experiment_id": record.experiment_id,
        "name": record.name,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "source_type": record.source_type,
        "source_description": record.source_description,
        "profile_id": record.profile_id,
        "algorithm_versions": dict(record.algorithm_versions),
        "samples": grouped,
    }
    if metric_definitions is not None:
        used = {sample.metric for sample in record.samples}
        document["metric_definitions"] = {
            name: dict(metric_definitions[name])
            for name in sorted(used)
            if name in metric_definitions
        }
    return document


def csv_rows(record: ExperimentRecord) -> list[list[object]]:
    """Header plus one row per sample. ``None`` is exported as ``N/A``."""
    rows: list[list[object]] = [list(_CSV_COLUMNS)]
    for sample in record.samples:
        rows.append(
            [
                record.name,
                record.experiment_id,
                record.started_at,
                record.finished_at or "",
                record.source_type,
                record.source_description,
                record.profile_id or "",
                sample.algorithm,
                record.algorithm_versions.get(sample.algorithm, ""),
                sample.metric,
                "N/A" if sample.value is None else sample.value,
                sample.unit,
                sample.note,
            ]
        )
    return rows


@runtime_checkable
class ResultsRepository(Protocol):
    def start_experiment(self, name: str, context: ExperimentContext | None = None) -> str:
        """Begin an experiment and return its id."""

    def record_metric(
        self,
        experiment_id: str,
        algorithm: str,
        metric: str,
        value: float | None,
        unit: str = "",
        note: str = "",
    ) -> None:
        """Record one measured value, or ``None`` plus a note when not applicable.

        Callers must not record values they did not measure.
        """

    def finish_experiment(self, experiment_id: str) -> None:
        """Close an experiment so no further samples are accepted."""

    def get_experiment(self, experiment_id: str) -> ExperimentRecord | None:
        """Return a record, or ``None`` when no such experiment exists."""

    def list_experiments(self) -> list[ExperimentRecord]:
        """All known experiments, most recently started first."""

    def export_csv(self, experiment_id: str, path: str) -> str:
        """Write CSV and return the path actually written."""

    def export_json(self, experiment_id: str, path: str) -> str:
        """Write JSON and return the path actually written."""
