"""Experiment Results panel.

The operator starts an experiment before measuring, and the panel shows the
live per-algorithm summary while it runs. Finishing writes the summary samples
to the results repository; those are what CSV and JSON export later.

Two honesty rules shape the table:

* a metric that could not be measured is shown as ``N/A`` with its reason in
  the Note column — never as zero;
* nothing is exported from the live session, only from the recorded file, so an
  exported document cannot disagree with what was measured.

No frame, image or video is ever saved.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..container import AppServices
from ..experiment import METRIC_DEFINITIONS
from ..interfaces import ExperimentContext, ExperimentRecord, MetricSample
from ..state import AppStateSnapshot
from . import widgets

__all__ = ["ResultsPanel"]

_log = logging.getLogger(__name__)

_MUTED = "color: #5b6470;"

_SOURCE_LABELS = {
    "synthetic": "Synthetic camera",
    "file": "Simulation video file",
    "tello": "Tello camera",
}


class ResultsPanel(QWidget):
    def __init__(self, services: AppServices, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._experiment_id: str | None = None
        self._finished: ExperimentRecord | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh_live)
        self._build()
        self.apply_state(services.state.snapshot())

    # -- construction --------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(widgets.SectionTitle("Experiment Results"))

        controls = QHBoxLayout()
        self._name_edit = QLineEdit(self)
        self._name_edit.setPlaceholderText("Experiment name")
        self._start_button = QPushButton("Start experiment")
        self._start_button.clicked.connect(self._on_start)
        self._finish_button = QPushButton("Finish")
        self._finish_button.setEnabled(False)
        self._finish_button.clicked.connect(self._on_finish)
        controls.addWidget(self._name_edit, 1)
        controls.addWidget(self._start_button)
        controls.addWidget(self._finish_button)
        layout.addLayout(controls)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._meta = QLabel("")
        self._meta.setWordWrap(True)
        self._meta.setStyleSheet(_MUTED)
        layout.addWidget(self._meta)

        self._empty_state = widgets.EmptyState(
            "No experiment recorded",
            "Measurements taken during a dry run or a tracking session appear here "
            "with their algorithm, metric, value and unit.",
            (
                "Start a video source and configure the detectors you want to compare.",
                "Start an experiment, then run a dry run or a tracking session.",
                "Finish the experiment and export the measurements as CSV or JSON.",
            ),
        )
        layout.addWidget(self._empty_state)

        self._table = QTableWidget(0, 5, self)
        self._table.setHorizontalHeaderLabels(["Algorithm", "Metric", "Value", "Unit", "Note"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setVisible(False)
        layout.addWidget(self._table, 1)

        buttons = QHBoxLayout()
        self._export_csv_button = QPushButton("Export CSV…")
        self._export_json_button = QPushButton("Export JSON…")
        self._export_csv_button.clicked.connect(lambda: self.export_csv())
        self._export_json_button.clicked.connect(lambda: self.export_json())
        for button in (self._export_csv_button, self._export_json_button):
            button.setEnabled(False)
            button.setToolTip("Finish an experiment before exporting it.")
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        disclaimer = QLabel(
            "Only measured values are recorded. Unavailable or not-applicable metrics "
            "are exported as N/A with the reason, never as zero. Video and images are "
            "never saved automatically."
        )
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(_MUTED)
        layout.addWidget(disclaimer)

    # -- experiment lifecycle ------------------------------------------------

    def start_experiment(self, name: str | None = None) -> str:
        """Start recording; returns the experiment id."""
        chosen = (name if name is not None else self._name_edit.text()).strip()
        if not chosen:
            chosen = f"Session {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        experiment_id = self._services.experiment.start(chosen, self._context())
        self._experiment_id = experiment_id
        self._finished = None
        self._name_edit.setText(chosen)
        self._name_edit.setEnabled(False)
        self._start_button.setEnabled(False)
        self._finish_button.setEnabled(True)
        self._export_csv_button.setEnabled(False)
        self._export_json_button.setEnabled(False)
        self._timer.start()
        self._refresh_live()
        self._status.setText(f"Recording '{chosen}'. Measurements appear as they arrive.")
        _log.info(
            "Experiment started",
            extra={"context": {"experiment_id": experiment_id, "name": chosen}},
        )
        return experiment_id

    def finish_experiment(self) -> ExperimentRecord | None:
        """Close the running experiment and show its recorded samples."""
        if self._experiment_id is None:
            return None
        record = self._services.experiment.finish()
        self._timer.stop()
        self._experiment_id = None
        self._finished = record
        self._name_edit.setEnabled(True)
        self._start_button.setEnabled(True)
        self._finish_button.setEnabled(False)
        if record is None:  # pragma: no cover - finish() only returns None when idle
            self._status.setText("The experiment had already been closed.")
            return None
        self._export_csv_button.setEnabled(True)
        self._export_json_button.setEnabled(True)
        self._export_csv_button.setToolTip("Save the recorded measurements as CSV.")
        self._export_json_button.setToolTip("Save the recorded measurements as JSON.")
        self._fill_from_samples(record)
        self._status.setText(
            f"Experiment '{record.name}' finished with {len(record.samples)} recorded "
            "measurement(s). Export is now available."
        )
        self._update_meta(record)
        _log.info(
            "Experiment finished",
            extra={
                "context": {
                    "experiment_id": record.experiment_id,
                    "samples": len(record.samples),
                }
            },
        )
        return record

    def shutdown(self) -> None:
        """Finish a running experiment so its measurements are not lost."""
        if self._experiment_id is not None:
            _log.info("Closing application; finishing the running experiment")
            self.finish_experiment()
        self._timer.stop()

    # -- live view -----------------------------------------------------------

    def _refresh_live(self) -> None:
        if self._experiment_id is None:
            return
        values = self._services.experiment.summary()
        rows = [
            (
                value.algorithm,
                value.definition.label,
                value.display_value(),
                value.unit,
                value.note,
            )
            for value in values
        ]
        self._fill_rows(rows)
        if not rows:
            self._status.setText(
                "Recording. No measurement yet — run a dry run or start a video source."
            )
            return
        not_applicable = sum(1 for value in values if not value.applicable)
        suffix = (
            f" {not_applicable} not applicable (see Note)." if not_applicable else ""
        )
        self._status.setText(
            f"Recording '{self._services.experiment.name}'. "
            f"{len(values)} live metric(s).{suffix}"
        )

    def _fill_from_samples(self, record: ExperimentRecord) -> None:
        rows = [
            (
                sample.algorithm,
                _metric_label(sample.metric),
                "N/A" if sample.value is None else _format_value(sample),
                sample.unit,
                sample.note,
            )
            for sample in record.samples
        ]
        self._fill_rows(rows)

    def _fill_rows(self, rows: list[tuple[str, str, str, str, str]]) -> None:
        self._empty_state.setVisible(not rows)
        self._table.setVisible(bool(rows))
        self._table.setRowCount(len(rows))
        for row, (algorithm, metric, value, unit, note) in enumerate(rows):
            for column, text in enumerate((algorithm, metric, value, unit, note)):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self._table.setItem(row, column, item)
        self._table.resizeColumnsToContents()

    # -- exports -------------------------------------------------------------

    def export_csv(self, path: str | None = None) -> str | None:
        return self._export("csv", path)

    def export_json(self, path: str | None = None) -> str | None:
        return self._export("json", path)

    def _export(self, kind: str, path: str | None) -> str | None:
        record = self._finished
        if record is None:
            self._status.setText("Finish the experiment before exporting it.")
            return None
        destination = path
        if destination is None:
            suggested = f"{record.name.replace(' ', '-').lower()}-{record.experiment_id}"
            suffix = "CSV files (*.csv);;All files (*)" if kind == "csv" else (
                "JSON files (*.json);;All files (*)"
            )
            destination, _ = QFileDialog.getSaveFileName(
                self,
                f"Export {kind.upper()}",
                f"{suggested}.{kind}",
                suffix,
            )
            if not destination:
                return None
        try:
            if kind == "csv":
                written = self._services.results.export_csv(record.experiment_id, destination)
            else:
                written = self._services.results.export_json(record.experiment_id, destination)
        except Exception as exc:  # noqa: BLE001 - reported to the operator
            _log.exception("Experiment export failed")
            widgets.show_error(self, "Export", exc)
            return None
        self._status.setText(f"Exported to {written}.")
        return written

    # -- state ---------------------------------------------------------------

    def apply_state(self, snapshot: AppStateSnapshot) -> None:
        if self._experiment_id is not None:
            return
        source_type = snapshot.video_source_type
        source = _SOURCE_LABELS.get(source_type or "", "No video source")
        profile = snapshot.active_profile_id or "none"
        self._meta.setText(f"Source: {source} · Profile: {profile}")

    # -- handlers ------------------------------------------------------------

    def _on_start(self) -> None:
        try:
            self.start_experiment()
        except Exception as exc:  # noqa: BLE001 - reported to the operator
            widgets.show_error(self, "Start experiment", exc)

    def _on_finish(self) -> None:
        self.finish_experiment()

    def _context(self) -> ExperimentContext:
        snapshot = self._services.state.snapshot()
        versions = {
            kind.value: detector.name
            for kind, detector in self._services.detectors.items()
            if detector is not None
        }
        source_type = snapshot.video_source_type or "none"
        return ExperimentContext(
            source_type=source_type,
            source_description=_SOURCE_LABELS.get(source_type, "No video source"),
            profile_id=snapshot.active_profile_id,
            algorithm_versions=versions,
        )

    def _update_meta(self, record: ExperimentRecord) -> None:
        versions = ", ".join(f"{key}={value}" for key, value in sorted(
            record.algorithm_versions.items()
        ))
        self._meta.setText(
            f"{record.name} · started {record.started_at} · "
            f"source {record.source_type or 'none'} · "
            f"profile {record.profile_id or 'none'}"
            + (f" · {versions}" if versions else "")
        )

    # -- accessors used by tests --------------------------------------------

    @property
    def table(self) -> QTableWidget:
        return self._table

    @property
    def empty_state(self) -> widgets.EmptyState:
        return self._empty_state

    @property
    def status_text(self) -> str:
        return self._status.text()

    @property
    def meta_text(self) -> str:
        return self._meta.text()

    @property
    def start_button(self) -> QPushButton:
        return self._start_button

    @property
    def finish_button(self) -> QPushButton:
        return self._finish_button

    @property
    def name_edit(self) -> QLineEdit:
        return self._name_edit

    @property
    def export_csv_button(self) -> QPushButton:
        return self._export_csv_button

    @property
    def export_json_button(self) -> QPushButton:
        return self._export_json_button

    @property
    def finished_record(self) -> ExperimentRecord | None:
        return self._finished


def _metric_label(metric: str) -> str:
    definition = METRIC_DEFINITIONS.get(metric)
    return definition.label if definition is not None else metric


def _format_value(sample: MetricSample) -> str:
    definition = METRIC_DEFINITIONS.get(sample.metric)
    if sample.value is None:  # pragma: no cover - callers check first
        return "N/A"
    precision = definition.precision if definition is not None else 2
    if precision == 0:
        return f"{sample.value:.0f}"
    return f"{sample.value:.{precision}f}"
