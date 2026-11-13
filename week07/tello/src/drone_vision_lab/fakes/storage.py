"""In-memory profile and results repositories.

The behaviour matches the on-disk adapters: the same validation, the same
not-applicable rule, the same export documents. Tests that exercise the
contract therefore run without touching the filesystem, and the UI can be
driven with either implementation.
"""

from __future__ import annotations

import csv
import json
import math
import threading
from datetime import UTC, datetime
from pathlib import Path

from ..errors import ConfigurationError
from ..experiment import metric_definitions_document
from ..interfaces.profiles import PROFILE_SCHEMA_VERSION, Profile
from ..interfaces.results import (
    ExperimentContext,
    ExperimentRecord,
    MetricSample,
    csv_rows,
    experiment_to_document,
)

__all__ = ["InMemoryProfileRepository", "InMemoryResultsRepository"]


class InMemoryProfileRepository:
    def __init__(self) -> None:
        self._profiles: dict[str, Profile] = {}

    def list_profiles(self) -> list[Profile]:
        return sorted(self._profiles.values(), key=lambda p: p.name.lower())

    def get(self, profile_id: str) -> Profile | None:
        return self._profiles.get(profile_id)

    def save(self, profile: Profile) -> None:
        if profile.schema_version != PROFILE_SCHEMA_VERSION:
            raise ConfigurationError(
                f"Unsupported profile schema version {profile.schema_version}",
                user_message=(
                    f"Profile '{profile.name}' uses schema version "
                    f"{profile.schema_version}, which this build cannot read."
                ),
            )
        now = datetime.now(UTC).isoformat(timespec="seconds")
        self._profiles[profile.profile_id] = Profile(
            profile_id=profile.profile_id,
            name=profile.name,
            schema_version=profile.schema_version,
            created_at=profile.created_at or now,
            updated_at=now,
            payload=dict(profile.payload),
        )

    def delete(self, profile_id: str) -> None:
        self._profiles.pop(profile_id, None)

    def duplicate(self, profile_id: str, new_name: str) -> Profile:
        source = self._profiles.get(profile_id)
        if source is None:
            raise ConfigurationError(
                f"No such profile: {profile_id}",
                user_message="The selected profile no longer exists.",
            )
        clone = Profile(
            profile_id=f"{profile_id}-copy-{len(self._profiles) + 1}",
            name=new_name,
            schema_version=source.schema_version,
            payload=dict(source.payload),
        )
        self.save(clone)
        stored = self._profiles[clone.profile_id]
        return stored


class InMemoryResultsRepository:
    def __init__(self) -> None:
        self._experiments: dict[str, ExperimentRecord] = {}
        self._lock = threading.RLock()

    def start_experiment(self, name: str, context: ExperimentContext | None = None) -> str:
        clean_name = name.strip()
        if not clean_name:
            raise ConfigurationError(
                "Experiment name must not be empty",
                user_message="Enter a name for the experiment first.",
            )
        with self._lock:
            experiment_id = f"exp-{len(self._experiments) + 1}"
            self._experiments[experiment_id] = ExperimentRecord(
                experiment_id=experiment_id,
                name=clean_name,
                source_type=context.source_type if context else "",
                source_description=context.source_description if context else "",
                profile_id=context.profile_id if context else None,
                algorithm_versions=dict(context.algorithm_versions) if context else {},
                started_at=_now(),
                finished_at=None,
                samples=(),
            )
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
        if value is not None and (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
        ):
            raise ConfigurationError(
                f"Metric {metric!r} value is not a finite number: {value!r}",
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
            self._experiments[experiment_id] = _replace_samples(
                record, (*record.samples, sample)
            )

    def finish_experiment(self, experiment_id: str) -> None:
        with self._lock:
            record = self._require(experiment_id)
            if record.open:
                self._experiments[experiment_id] = _replace_finished(record, _now())

    def get_experiment(self, experiment_id: str) -> ExperimentRecord | None:
        with self._lock:
            return self._experiments.get(experiment_id)

    def list_experiments(self) -> list[ExperimentRecord]:
        with self._lock:
            return sorted(
                self._experiments.values(),
                key=lambda record: (record.started_at, record.experiment_id),
                reverse=True,
            )

    def export_csv(self, experiment_id: str, path: str) -> str:
        record = self._require(experiment_id)
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(csv_rows(record))
        return str(destination)

    def export_json(self, experiment_id: str, path: str) -> str:
        record = self._require(experiment_id)
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        document = experiment_to_document(
            record, metric_definitions=metric_definitions_document()
        )
        with destination.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
        return str(destination)

    def _require(self, experiment_id: str) -> ExperimentRecord:
        try:
            return self._experiments[experiment_id]
        except KeyError as exc:
            raise ConfigurationError(
                f"No such experiment: {experiment_id}",
                user_message="The selected experiment no longer exists.",
            ) from exc


def _replace_samples(
    record: ExperimentRecord, samples: tuple[MetricSample, ...]
) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=record.experiment_id,
        name=record.name,
        source_type=record.source_type,
        source_description=record.source_description,
        profile_id=record.profile_id,
        algorithm_versions=record.algorithm_versions,
        started_at=record.started_at,
        finished_at=record.finished_at,
        samples=samples,
        schema_version=record.schema_version,
    )


def _replace_finished(record: ExperimentRecord, finished_at: str) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=record.experiment_id,
        name=record.name,
        source_type=record.source_type,
        source_description=record.source_description,
        profile_id=record.profile_id,
        algorithm_versions=record.algorithm_versions,
        started_at=record.started_at,
        finished_at=finished_at,
        samples=record.samples,
        schema_version=record.schema_version,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
