"""On-disk experiment repository.

One JSON document per experiment under ``results_dir()``. Every metric sample is
written immediately, so a crash mid-experiment loses at most the sample being
recorded. Exports are produced from the stored document, never from the live
session, so an exported file cannot disagree with what was measured.

Nothing here stores frames, images or video.
"""

from __future__ import annotations

import csv
import json
import logging
import math
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...config import results_dir
from ...errors import ConfigurationError
from ...experiment import metric_definitions_document
from ...interfaces.results import (
    EXPERIMENT_SCHEMA_VERSION,
    ExperimentContext,
    ExperimentRecord,
    MetricSample,
    csv_rows,
    experiment_to_document,
)
from .profile_document import atomic_write_json, read_json_document, validate_profile_id

__all__ = ["JsonResultsRepository"]

_log = logging.getLogger(__name__)


class JsonResultsRepository:
    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else results_dir()
        self._lock = threading.RLock()

    @property
    def root(self) -> Path:
        return self._root

    # -- lifecycle -----------------------------------------------------------

    def start_experiment(self, name: str, context: ExperimentContext | None = None) -> str:
        clean_name = name.strip()
        if not clean_name:
            raise ConfigurationError(
                "Experiment name must not be empty",
                user_message="Enter a name for the experiment first.",
            )
        with self._lock:
            experiment_id = self._new_id()
            record = ExperimentRecord(
                experiment_id=experiment_id,
                name=clean_name,
                source_type=(context.source_type if context else ""),
                source_description=(context.source_description if context else ""),
                profile_id=(context.profile_id if context else None),
                algorithm_versions=dict(context.algorithm_versions) if context else {},
                started_at=_now(),
                finished_at=None,
                samples=(),
            )
            self._write(record)
            return experiment_id

    def record_metric(
        self,
        experiment_id: str,
        algorithm: str,
        metric: str,
        value: float | None,
        unit: str = "",
        note: str = "",
    ) -> None:
        if value is None and not note:
            raise ConfigurationError(
                f"Metric {metric!r} has no value and no note",
                user_message=(
                    "A metric that was not measured must say why. "
                    "Record it as not applicable with an explanation instead of zero."
                ),
            )
        if value is not None:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ConfigurationError(
                    f"Metric {metric!r} value is not a number: {value!r}",
                    user_message="Only numeric measurements can be recorded.",
                )
            if not math.isfinite(float(value)):
                raise ConfigurationError(
                    f"Metric {metric!r} value is not finite: {value!r}",
                    user_message="Only finite numeric measurements can be recorded.",
                )

        with self._lock:
            record = self._require(experiment_id)
            if not record.open:
                raise ConfigurationError(
                    "Cannot record metrics on a finished experiment",
                    user_message="This experiment has already been closed.",
                )
            sample = MetricSample(
                algorithm=algorithm,
                metric=metric,
                value=None if value is None else float(value),
                unit=unit,
                note=note,
            )
            self._write(
                ExperimentRecord(
                    experiment_id=record.experiment_id,
                    name=record.name,
                    source_type=record.source_type,
                    source_description=record.source_description,
                    profile_id=record.profile_id,
                    algorithm_versions=record.algorithm_versions,
                    started_at=record.started_at,
                    finished_at=record.finished_at,
                    samples=(*record.samples, sample),
                )
            )

    def finish_experiment(self, experiment_id: str) -> None:
        with self._lock:
            record = self._require(experiment_id)
            if not record.open:
                return
            self._write(
                ExperimentRecord(
                    experiment_id=record.experiment_id,
                    name=record.name,
                    source_type=record.source_type,
                    source_description=record.source_description,
                    profile_id=record.profile_id,
                    algorithm_versions=record.algorithm_versions,
                    started_at=record.started_at,
                    finished_at=_now(),
                    samples=record.samples,
                )
            )

    # -- reads ---------------------------------------------------------------

    def get_experiment(self, experiment_id: str) -> ExperimentRecord | None:
        path = self._path(experiment_id)
        if not path.exists():
            return None
        return self._load_file(path)

    def list_experiments(self) -> list[ExperimentRecord]:
        if not self._root.exists():
            return []
        records: list[ExperimentRecord] = []
        for path in sorted(self._root.glob("*.json")):
            try:
                records.append(self._load_file(path))
            except (ConfigurationError, OSError) as exc:
                _log.warning(
                    "Skipping invalid experiment file",
                    extra={
                        "context": {
                            "path": str(path),
                            "reason": getattr(exc, "user_message", str(exc)),
                        }
                    },
                )
        return sorted(
            records,
            key=lambda record: (record.started_at, record.experiment_id),
            reverse=True,
        )

    # -- exports -------------------------------------------------------------

    def export_csv(self, experiment_id: str, path: str) -> str:
        record = self._require(experiment_id)
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerows(csv_rows(record))
        except OSError as exc:
            raise ConfigurationError(
                f"Could not write {destination}: {exc}",
                user_message=f"The CSV file could not be written to '{destination}' ({exc}).",
            ) from exc
        return str(destination)

    def export_json(self, experiment_id: str, path: str) -> str:
        record = self._require(experiment_id)
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        document = experiment_to_document(
            record, metric_definitions=metric_definitions_document()
        )
        try:
            with destination.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(document, handle, indent=2, sort_keys=True)
                handle.write("\n")
        except OSError as exc:
            raise ConfigurationError(
                f"Could not write {destination}: {exc}",
                user_message=f"The JSON file could not be written to '{destination}' ({exc}).",
            ) from exc
        return str(destination)

    # -- internals -----------------------------------------------------------

    def _path(self, experiment_id: str) -> Path:
        return self._root / f"{_validate_experiment_id(experiment_id)}.json"

    def _write(self, record: ExperimentRecord) -> None:
        document = experiment_to_document(
            record, metric_definitions=metric_definitions_document()
        )
        try:
            atomic_write_json(self._path(record.experiment_id), document)
        except OSError as exc:
            raise ConfigurationError(
                f"Could not write experiment {record.experiment_id!r}: {exc}",
                user_message=f"The experiment could not be saved to '{self._root}' ({exc}).",
            ) from exc

    def _load_file(self, path: Path) -> ExperimentRecord:
        document = read_json_document(path)
        if not isinstance(document, dict):
            raise ConfigurationError(
                f"{path} is not a JSON object",
                user_message=f"The experiment file '{path.name}' is not valid.",
            )
        version = document.get("schema_version", EXPERIMENT_SCHEMA_VERSION)
        if isinstance(version, bool) or not isinstance(version, int):
            raise ConfigurationError(
                f"{path} has an invalid schema version",
                user_message=f"The experiment file '{path.name}' has an invalid format.",
            )
        if version > EXPERIMENT_SCHEMA_VERSION:
            raise ConfigurationError(
                f"{path} uses schema version {version}",
                user_message=(
                    f"The experiment file '{path.name}' was written by a newer build."
                ),
            )

        experiment_id = _require_str(document, "experiment_id", path)
        name = _require_str(document, "name", path)
        started_at = _require_str(document, "started_at", path)
        finished_at = document.get("finished_at")
        if finished_at is not None and not isinstance(finished_at, str):
            finished_at = None

        raw_samples = document.get("samples", {})
        if not isinstance(raw_samples, dict):
            raise ConfigurationError(
                f"{path} samples are not an object",
                user_message=f"The experiment file '{path.name}' has malformed samples.",
            )
        samples: list[MetricSample] = []
        try:
            for algorithm, entries in raw_samples.items():
                if not isinstance(entries, list):
                    raise ValueError(f"samples for {algorithm!r} are not a list")
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise ValueError("a sample is not an object")
                    value = entry.get("value")
                    if value is not None and (
                        not isinstance(value, (int, float)) or isinstance(value, bool)
                    ):
                        raise ValueError("a sample value is not numeric")
                    samples.append(
                        MetricSample(
                            algorithm=str(algorithm),
                            metric=str(entry.get("metric", "")),
                            value=None if value is None else float(value),
                            unit=str(entry.get("unit", "")),
                            note=str(entry.get("note", "")),
                        )
                    )
        except (ValueError, TypeError) as exc:
            raise ConfigurationError(
                f"{path} contains an invalid sample: {exc}",
                user_message=(
                    f"The experiment file '{path.name}' contains a malformed measurement."
                ),
            ) from exc

        versions = document.get("algorithm_versions", {})
        if not isinstance(versions, dict):
            versions = {}

        return ExperimentRecord(
            experiment_id=experiment_id,
            name=name,
            source_type=str(document.get("source_type") or ""),
            source_description=str(document.get("source_description") or ""),
            profile_id=(
                document.get("profile_id")
                if isinstance(document.get("profile_id"), str)
                else None
            ),
            algorithm_versions={
                str(key): str(value) for key, value in versions.items()
            },
            started_at=started_at,
            finished_at=finished_at,
            samples=tuple(samples),
            schema_version=version,
        )

    def _require(self, experiment_id: str) -> ExperimentRecord:
        record = self.get_experiment(experiment_id)
        if record is None:
            raise ConfigurationError(
                f"No such experiment: {experiment_id}",
                user_message="The selected experiment no longer exists.",
            )
        return record

    def _new_id(self) -> str:
        stamp = datetime.now(UTC).strftime("exp-%Y%m%d-%H%M%S")
        candidate = f"{stamp}-1"
        counter = 2
        while self._path(candidate).exists():
            candidate = f"{stamp}-{counter}"
            counter += 1
        return candidate


def _validate_experiment_id(experiment_id: str) -> str:
    """Experiment ids are file names too; the profile rules are exactly right."""
    try:
        return validate_profile_id(experiment_id)
    except ConfigurationError:
        raise ConfigurationError(
            f"Invalid experiment id: {experiment_id!r}",
            user_message="The experiment id is not usable as a file name.",
        ) from None


def _require_str(document: dict[str, Any], key: str, path: Path) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigurationError(
            f"{path} is missing {key!r}",
            user_message=f"The experiment file '{path.name}' is missing its {key}.",
        )
    return value


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
