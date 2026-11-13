"""Deterministic SDK doubles. No network, no key, no real genai.Client."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeUploadedFile:
    name: str = "files/fake-123"
    uri: str = "https://generativelanguage.googleapis.com/v1beta/files/fake-123"
    mime_type: str = "audio/wav"
    state: str = "ACTIVE"


@dataclass
class FakeInteraction:
    id: str = "interaction-1"
    status: str = "completed"
    output_text: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)

    def model_dump(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "output_text": self.output_text,
            "steps": self.steps,
        }


class FakeFiles:
    def __init__(self, uploaded: FakeUploadedFile | None = None) -> None:
        self.file = uploaded or FakeUploadedFile()
        self.upload_calls: list[dict[str, Any]] = []
        self.get_calls: list[str] = []
        self.deleted: list[str] = []
        self.fail_delete = False
        self.fail_upload: Exception | None = None
        self.states: list[str] = []

    def upload(self, *, file: str, config: dict[str, Any]) -> FakeUploadedFile:
        self.upload_calls.append({"file": file, "config": config})
        if self.fail_upload is not None:
            raise self.fail_upload
        return self.file

    def get(self, *, name: str) -> FakeUploadedFile:
        self.get_calls.append(name)
        if self.states:
            self.file.state = self.states.pop(0)
        return self.file

    def delete(self, *, name: str) -> dict[str, Any]:
        if self.fail_delete:
            raise RuntimeError("simulated delete failure")
        self.deleted.append(name)
        return {"name": name, "deleted": True}


class FakeInteractions:
    def __init__(self, interaction: FakeInteraction | None = None) -> None:
        self.interaction = interaction or FakeInteraction()
        self.bodies: list[dict[str, Any]] = []
        self.error: Exception | None = None

    def create(self, *, timeout: float, **body: Any) -> FakeInteraction:
        self.bodies.append({"timeout": timeout, **body})
        if self.error is not None:
            raise self.error
        return self.interaction


class FakeSDK:
    def __init__(
        self,
        interaction: FakeInteraction | None = None,
        uploaded: FakeUploadedFile | None = None,
    ) -> None:
        self.files = FakeFiles(uploaded)
        self.interactions = FakeInteractions(interaction)
