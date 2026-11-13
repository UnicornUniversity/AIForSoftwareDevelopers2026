"""Profile manager: create, rename, duplicate, delete, save and load.

A profile is a portable JSON file, so everything here is reversible except
delete — and delete asks first, naming the exact file it will remove.

Loading a profile installs detector configuration into the running application.
It never starts a video source, never loads a model over the network and never
sends a command to the aircraft.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..adapters.storage import slugify_profile_name
from ..adapters.vision import OpenCvDetectorConfig, OpenCvTargetDetector, YoloDetector
from ..adapters.vision.yolo_detector import YoloDetectorConfig
from ..adapters.vlm import OllamaVlmDetector
from ..adapters.vlm.vlm_detector import VlmConfig
from ..container import AppServices
from ..domain import DetectorKind
from ..errors import user_message
from ..interfaces import Profile
from . import widgets

__all__ = ["ProfilesDialog", "apply_profile"]

_log = logging.getLogger(__name__)

_MUTED = "color: #5b6470;"


def apply_profile(services: AppServices, profile: Profile) -> str:
    """Apply a profile's settings to the running application.

    Returns a human-readable summary of what was applied and what failed. A
    broken section is reported and skipped; it never blocks the other sections
    and it never falls back to a different model than the profile names.
    """
    payload = profile.payload
    applied: list[str] = []
    problems: list[str] = []

    opencv_data = payload.get("opencv")
    if isinstance(opencv_data, dict):
        _apply_detector(
            services,
            DetectorKind.OPENCV,
            opencv_data,
            OpenCvDetectorConfig.from_dict,
            OpenCvTargetDetector,
            "OpenCV calibration",
            applied,
            problems,
        )

    yolo_data = payload.get("yolo")
    if isinstance(yolo_data, dict):
        _apply_detector(
            services,
            DetectorKind.YOLO,
            yolo_data,
            YoloDetectorConfig.from_dict,
            YoloDetector,
            "YOLO settings",
            applied,
            problems,
        )

    vlm_data = payload.get("vlm")
    if isinstance(vlm_data, dict):
        try:
            config = VlmConfig.from_dict(vlm_data)
            existing = services.detectors.get(DetectorKind.VLM)
            if isinstance(existing, OllamaVlmDetector):
                existing.update_config(config)
            else:
                services.detectors[DetectorKind.VLM] = OllamaVlmDetector(config)
            services.detector_events.publish(DetectorKind.VLM)
            applied.append("VLM settings (check the service before use)")
        except Exception as exc:  # noqa: BLE001 - reported, never fatal
            problems.append(f"VLM: {user_message(exc)}")

    if isinstance(payload.get("source"), dict):
        kind = payload["source"].get("kind")
        if isinstance(kind, str):
            problems.append(
                f"Source '{kind}' was not started automatically; choose it in the Vision Lab."
            )

    if not applied and not problems:
        return f"Profile '{profile.name}' contains no settings yet."

    parts: list[str] = []
    if applied:
        parts.append("Applied: " + ", ".join(applied) + ".")
    if problems:
        parts.append("Not applied: " + "; ".join(problems) + ".")
    return " ".join(parts)


def _apply_detector(
    services: AppServices,
    kind: DetectorKind,
    data: dict[str, Any],
    make_config: Callable[[dict[str, Any]], Any],
    detector_type: Any,
    label: str,
    applied: list[str],
    problems: list[str],
) -> None:
    try:
        config = make_config(data)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        problems.append(f"{label}: {user_message(exc)}")
        return

    existing = services.detectors.get(kind)
    if isinstance(existing, detector_type):
        existing.update_config(config)
        detector = existing
    else:
        detector = detector_type(config)
        services.detectors[kind] = detector

    try:
        detector.load()
    except Exception as exc:  # noqa: BLE001 - a missing model is a normal outcome
        problems.append(f"{label}: {user_message(exc)}")
    else:
        applied.append(label)
    finally:
        # The slot changed whether or not the model loaded; every tab that
        # gates on it must re-read the new state, including a failed load.
        services.detector_events.publish(kind)


class ProfilesDialog(QDialog):
    """Modal profile manager opened from the File menu."""

    def __init__(self, services: AppServices, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._profiles: list[Profile] = []
        self.setWindowTitle("Experiment Profiles")
        widgets.fit_initial_size(self, 640, 460, factor=0.85)
        self._build()
        self.refresh()

    # -- construction --------------------------------------------------------

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        left = QVBoxLayout()
        left.addWidget(widgets.SectionTitle("Profiles"))
        self._list = QListWidget(self)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        left.addWidget(self._list, 1)
        layout.addLayout(left, 1)

        right = QVBoxLayout()
        self._details = QLabel("")
        self._details.setWordWrap(True)
        self._details.setStyleSheet(_MUTED)
        right.addWidget(widgets.SectionTitle("Details"))
        right.addWidget(self._details)
        right.addStretch(1)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        right.addWidget(self._status)

        buttons = [
            ("New…", self._on_new),
            ("Rename…", self._on_rename),
            ("Duplicate…", self._on_duplicate),
            ("Save current settings", self._on_save_current),
            ("Load", self._on_load),
            ("Delete…", self._on_delete),
        ]
        self._buttons: dict[str, QPushButton] = {}
        for label, handler in buttons:
            button = QPushButton(label)
            button.clicked.connect(handler)
            right.addWidget(button)
            self._buttons[label] = button

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        right.addWidget(close)

        layout.addLayout(right, 1)

    # -- public operations (also used by tests) ------------------------------

    @property
    def profiles(self) -> list[Profile]:
        return list(self._profiles)

    @property
    def list_widget(self) -> QListWidget:
        return self._list

    @property
    def details_text(self) -> str:
        return self._details.text()

    @property
    def status_text(self) -> str:
        return self._status.text()

    @property
    def buttons(self) -> dict[str, QPushButton]:
        return dict(self._buttons)

    @property
    def selected_profile(self) -> Profile | None:
        item = self._list.currentItem()
        if item is None:
            return None
        profile_id = item.data(Qt.ItemDataRole.UserRole)
        return next((p for p in self._profiles if p.profile_id == profile_id), None)

    def refresh(self) -> None:
        selected = self.selected_profile
        self._profiles = self._services.profiles.list_profiles()
        active = self._services.state.snapshot().active_profile_id
        self._list.blockSignals(True)
        self._list.clear()
        try:
            for profile in self._profiles:
                label = profile.name + ("  (active)" if profile.profile_id == active else "")
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, profile.profile_id)
                item.setToolTip(
                    f"{profile.profile_id}.json · schema {profile.schema_version}"
                )
                self._list.addItem(item)
                if selected is not None and profile.profile_id == selected.profile_id:
                    self._list.setCurrentItem(item)
        finally:
            self._list.blockSignals(False)
        if self._list.currentItem() is None and self._list.count():
            self._list.setCurrentRow(0)
        self._on_selection_changed()

    def create_profile(self, name: str) -> Profile:
        clean = name.strip()
        profile = Profile(
            profile_id=self._unique_id(clean),
            name=clean,
            payload={},
        )
        self._services.profiles.save(profile)
        self._set_status(f"Created profile '{clean}'.")
        self.refresh()
        self._select(profile.profile_id)
        return profile

    def rename_selected(self, new_name: str) -> Profile | None:
        profile = self.selected_profile
        if profile is None:
            return None
        clean = new_name.strip()
        updated = Profile(
            profile_id=profile.profile_id,
            name=clean,
            schema_version=profile.schema_version,
            created_at=profile.created_at,
            payload=dict(profile.payload),
        )
        self._services.profiles.save(updated)
        self._set_status(f"Renamed profile to '{clean}'.")
        self.refresh()
        self._select(profile.profile_id)
        return self._services.profiles.get(profile.profile_id)

    def duplicate_selected(self, new_name: str) -> Profile | None:
        profile = self.selected_profile
        if profile is None:
            return None
        clone = self._services.profiles.duplicate(profile.profile_id, new_name.strip())
        self._set_status(f"Duplicated '{profile.name}' as '{clone.name}'.")
        self.refresh()
        self._select(clone.profile_id)
        return clone

    def delete_selected(self) -> None:
        profile = self.selected_profile
        if profile is None:
            return
        self._services.profiles.delete(profile.profile_id)
        if self._services.state.snapshot().active_profile_id == profile.profile_id:
            self._services.state.update(active_profile_id=None)
        self._set_status(f"Deleted profile '{profile.name}'.")
        self.refresh()

    def save_current_settings(self) -> None:
        target = self.selected_profile
        if target is None:
            self._set_status("Select a profile to save into.")
            return
        active_id = self._services.state.snapshot().active_profile_id
        if active_id is None:
            self._set_status(
                "No active profile. Load a profile first, or configure the detectors, "
                "then load this profile and save."
            )
            return
        source = self._services.profiles.get(active_id)
        if source is None:
            self._set_status("The active profile no longer exists.")
            return
        self._services.profiles.save(
            Profile(
                profile_id=target.profile_id,
                name=target.name,
                schema_version=target.schema_version,
                created_at=target.created_at,
                payload=dict(source.payload),
            )
        )
        self._set_status(f"Saved the active settings into '{target.name}'.")
        self.refresh()

    def load_selected(self) -> str:
        profile = self.selected_profile
        if profile is None:
            return "Select a profile to load."
        summary = apply_profile(self._services, profile)
        self._services.state.update(active_profile_id=profile.profile_id, last_error=None)
        self._set_status(summary)
        self.refresh()
        _log.info(
            "Profile loaded",
            extra={"context": {"profile_id": profile.profile_id, "name": profile.name}},
        )
        return summary

    def ask_name(self, title: str, prompt: str, initial: str = "") -> str | None:
        """Name prompt seam; overridden by tests to stay headless."""
        text, accepted = QInputDialog.getText(self, title, prompt, text=initial)
        if not accepted:
            return None
        if not text.strip():
            QMessageBox.warning(self, title, "A profile needs a name.")
            return None
        return text.strip()

    def confirm_delete(self, profile: Profile) -> bool:
        """Destructive-action confirmation; overridden by tests to stay headless."""
        answer = QMessageBox.question(
            self,
            "Delete profile",
            f"Delete profile '{profile.name}'?\n\n"
            f"This removes {profile.profile_id}.json from "
            f"{self._profiles_root()}. It cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return widgets.is_yes(answer)

    # -- button handlers -----------------------------------------------------

    def _on_new(self) -> None:
        name = self.ask_name("New profile", "Profile name:", "New profile")
        if name:
            self.create_profile(name)

    def _on_rename(self) -> None:
        profile = self.selected_profile
        if profile is None:
            return
        name = self.ask_name("Rename profile", "New name:", profile.name)
        if name:
            self.rename_selected(name)

    def _on_duplicate(self) -> None:
        profile = self.selected_profile
        if profile is None:
            return
        name = self.ask_name("Duplicate profile", "Name for the copy:", f"{profile.name} copy")
        if name:
            self.duplicate_selected(name)

    def _on_save_current(self) -> None:
        self.save_current_settings()

    def _on_load(self) -> None:
        self.load_selected()

    def _on_delete(self) -> None:
        profile = self.selected_profile
        if profile is None:
            return
        if not self.confirm_delete(profile):
            self._set_status("Delete cancelled; the profile was kept.")
            return
        self.delete_selected()

    # -- helpers -------------------------------------------------------------

    def _on_selection_changed(self, *_args: object) -> None:
        profile = self.selected_profile
        has_selection = profile is not None
        for label in ("Rename…", "Duplicate…", "Save current settings", "Load", "Delete…"):
            self._buttons[label].setEnabled(has_selection)
        if profile is None:
            self._details.setText("Select a profile to see what it stores.")
            return
        sections = sorted(str(key) for key in profile.payload)
        self._details.setText(
            f"<b>{profile.name}</b><br>"
            f"Id: {profile.profile_id} · schema {profile.schema_version}<br>"
            f"Created: {profile.created_at or 'unknown'}<br>"
            f"Updated: {profile.updated_at or 'unknown'}<br>"
            f"Settings: {', '.join(sections) if sections else 'none yet'}"
        )

    def _set_status(self, text: str) -> None:
        self._status.setText(text)

    def _select(self, profile_id: str) -> None:
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == profile_id:
                self._list.setCurrentRow(row)
                return

    def _unique_id(self, name: str) -> str:
        base = slugify_profile_name(name)
        existing = {profile.profile_id for profile in self._services.profiles.list_profiles()}
        candidate = base
        counter = 2
        while candidate in existing:
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    def _profiles_root(self) -> str:
        root = getattr(self._services.profiles, "root", None)
        return str(Path(root)) if root is not None else "the profile folder"
