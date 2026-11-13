"""Experiment profile repository interface.

Profiles are portable JSON documents holding calibration settings, selected
models and safe tracking parameters. They never contain credentials.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = ["Profile", "ProfileRepository", "PROFILE_SCHEMA_VERSION"]

PROFILE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class Profile:
    """A named, versioned bundle of settings."""

    profile_id: str
    name: str
    schema_version: int = PROFILE_SCHEMA_VERSION
    created_at: str = ""
    updated_at: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class ProfileRepository(Protocol):
    def list_profiles(self) -> list[Profile]: ...

    def get(self, profile_id: str) -> Profile | None: ...

    def save(self, profile: Profile) -> None:
        """Create or replace a profile. Raises on invalid schema."""

    def delete(self, profile_id: str) -> None: ...

    def duplicate(self, profile_id: str, new_name: str) -> Profile: ...
