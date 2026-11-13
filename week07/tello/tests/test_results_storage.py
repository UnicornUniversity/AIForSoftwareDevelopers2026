"""On-disk experiment results: persistence, metadata, N/A and exports."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from drone_vision_lab.adapters.storage import JsonResultsRepository
from drone_vision_lab.errors import ConfigurationError
from drone_vision_lab.interfaces import ExperimentContext


def _repo(tmp_path) -> JsonResultsRepository:
    return JsonResultsRepository(tmp_path / "results")


def _start(repo: JsonResultsRepository, name: str = "Demo") -> str:
    return repo.start_experiment(
        name,
        ExperimentContext(
            source_type="synthetic",
            source_description="Synthetic camera",
            profile_id="default",
            algorithm_versions={"opencv": "OpenCV colour threshold", "yolo": "YOLO11n"},
        ),
    )


def test_an_experiment_survives_a_restart(tmp_path):
    repo = _repo(tmp_path)
    experiment_id = _start(repo)
    repo.record_metric(experiment_id, "opencv", "frames_analyzed", 10, "count")
    repo.finish_experiment(experiment_id)

    reopened = _repo(tmp_path).get_experiment(experiment_id)

    assert reopened is not None
    assert reopened.name == "Demo"
    assert reopened.source_type == "synthetic"
    assert reopened.profile_id == "default"
    assert reopened.algorithm_versions["yolo"] == "YOLO11n"
    assert reopened.started_at
    assert reopened.finished_at
    assert reopened.open is False
    assert reopened.samples[0].value == 10.0


def test_an_open_experiment_is_marked_open(tmp_path):
    repo = _repo(tmp_path)
    experiment_id = _start(repo)

    record = repo.get_experiment(experiment_id)

    assert record is not None
    assert record.open is True
    assert record.finished_at is None


def test_metrics_are_recorded_in_order(tmp_path):
    repo = _repo(tmp_path)
    experiment_id = _start(repo)
    repo.record_metric(experiment_id, "opencv", "frames_analyzed", 5, "count")
    repo.record_metric(experiment_id, "opencv", "detection_rate", 0.5, "fraction")

    record = repo.get_experiment(experiment_id)

    assert record is not None
    assert [(sample.metric, sample.value) for sample in record.samples] == [
        ("frames_analyzed", 5.0),
        ("detection_rate", 0.5),
    ]


def test_a_not_applicable_metric_needs_a_reason(tmp_path):
    repo = _repo(tmp_path)
    experiment_id = _start(repo)

    with pytest.raises(ConfigurationError) as info:
        repo.record_metric(experiment_id, "opencv", "confidence_mean", None)
    assert "say why" in info.value.user_message

    repo.record_metric(
        experiment_id,
        "opencv",
        "confidence_mean",
        None,
        "ratio",
        "This algorithm reports no confidence score.",
    )
    record = repo.get_experiment(experiment_id)
    assert record is not None
    assert record.samples[0].value is None
    assert "confidence" in record.samples[0].note


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_measurements_are_refused(tmp_path, value):
    repo = _repo(tmp_path)
    experiment_id = _start(repo)

    with pytest.raises(ConfigurationError):
        repo.record_metric(experiment_id, "opencv", "fps", value, "Hz")


def test_no_metric_is_accepted_after_finishing(tmp_path):
    repo = _repo(tmp_path)
    experiment_id = _start(repo)
    repo.finish_experiment(experiment_id)

    with pytest.raises(ConfigurationError):
        repo.record_metric(experiment_id, "opencv", "fps", 1.0, "Hz")


def test_finishing_twice_keeps_the_first_finished_at(tmp_path):
    repo = _repo(tmp_path)
    experiment_id = _start(repo)
    repo.finish_experiment(experiment_id)
    first = repo.get_experiment(experiment_id)
    repo.finish_experiment(experiment_id)
    second = repo.get_experiment(experiment_id)

    assert first is not None and second is not None
    assert first.finished_at == second.finished_at


def test_unknown_experiment_raises_a_friendly_error(tmp_path):
    repo = _repo(tmp_path)

    assert repo.get_experiment("missing") is None
    with pytest.raises(ConfigurationError):
        repo.finish_experiment("missing")
    with pytest.raises(ConfigurationError):
        repo.export_csv("missing", str(tmp_path / "x.csv"))


def test_exports_carry_the_experiment_metadata(tmp_path):
    repo = _repo(tmp_path)
    experiment_id = _start(repo, "Ball tracking")
    repo.record_metric(experiment_id, "opencv", "frames_analyzed", 12, "count")
    repo.record_metric(
        experiment_id,
        "vlm",
        "confidence_mean",
        None,
        "ratio",
        "This algorithm reports no confidence score.",
    )
    repo.finish_experiment(experiment_id)

    csv_path = repo.export_csv(experiment_id, str(tmp_path / "out.csv"))
    with open(csv_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["experiment"] == "Ball tracking"
    assert rows[0]["experiment_id"] == experiment_id
    assert rows[0]["started_at"]
    assert rows[0]["source_type"] == "synthetic"
    assert rows[0]["profile_id"] == "default"
    assert rows[0]["algorithm_version"] == "OpenCV colour threshold"
    assert rows[1]["value"] == "N/A"
    assert rows[1]["note"]

    json_path = repo.export_json(experiment_id, str(tmp_path / "out.json"))
    document = json.loads(Path(json_path).read_text(encoding="utf-8"))

    assert document["name"] == "Ball tracking"
    assert document["source_description"] == "Synthetic camera"
    assert document["algorithm_versions"]["yolo"] == "YOLO11n"
    assert document["samples"]["vlm"][0]["value"] is None
    assert "confidence_mean" in document["metric_definitions"]
    assert "confidence" in document["metric_definitions"]["confidence_mean"]["description"]


def test_an_empty_experiment_still_exports_clean_metadata(tmp_path):
    repo = _repo(tmp_path)
    experiment_id = _start(repo, "Nothing measured")
    repo.finish_experiment(experiment_id)

    csv_path = repo.export_csv(experiment_id, str(tmp_path / "empty.csv"))
    with open(csv_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert len(rows) == 1  # header only: no measurement was invented
    assert rows[0][0] == "experiment"

    json_path = repo.export_json(experiment_id, str(tmp_path / "empty.json"))
    document = json.loads(Path(json_path).read_text(encoding="utf-8"))
    assert document["samples"] == {}
    assert document["finished_at"]


def test_list_experiments_returns_the_newest_first(tmp_path):
    repo = _repo(tmp_path)
    first = _start(repo, "First")
    repo.finish_experiment(first)
    second = _start(repo, "Second")
    repo.finish_experiment(second)

    names = [record.name for record in repo.list_experiments()]

    assert names == ["Second", "First"]


def test_invalid_experiment_files_are_skipped(tmp_path):
    repo = _repo(tmp_path)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "broken.json").write_text("{nope", encoding="utf-8")
    valid = _start(repo, "Valid")

    assert [record.experiment_id for record in repo.list_experiments()] == [valid]


def test_experiment_files_never_contain_image_data(tmp_path):
    repo = _repo(tmp_path)
    experiment_id = _start(repo)
    repo.record_metric(experiment_id, "opencv", "frames_analyzed", 1, "count")
    repo.finish_experiment(experiment_id)

    document = json.loads(
        (tmp_path / "results" / f"{experiment_id}.json").read_text(encoding="utf-8")
    )

    assert set(document) == {
        "schema_version",
        "experiment_id",
        "name",
        "started_at",
        "finished_at",
        "source_type",
        "source_description",
        "profile_id",
        "algorithm_versions",
        "samples",
        "metric_definitions",
    }
