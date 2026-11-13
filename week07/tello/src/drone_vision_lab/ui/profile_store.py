"""Write one settings section into the active profile.

Every settings dialog stores into the profile the operator loaded, not into a
hard-coded one. When no profile has been loaded, ``default`` is created on
first save so the previous single-profile behaviour is preserved.

The profile file stays the single source of truth: the dialog updates its own
detector in memory *and* writes the same settings here, so reopening the
application after loading that profile reproduces the same configuration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..container import AppServices
from ..interfaces import Profile

__all__ = [
    "DEFAULT_PROFILE_ID",
    "active_profile_id",
    "store_profile_section",
    "store_profile_section_if_active",
    "utc_timestamp",
]

DEFAULT_PROFILE_ID = "default"


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def active_profile_id(services: AppServices) -> str:
    return services.state.snapshot().active_profile_id or DEFAULT_PROFILE_ID


def store_profile_section(
    services: AppServices,
    section: str,
    data: dict[str, Any],
    *,
    extra: dict[str, Any] | None = None,
) -> str:
    """Merge one section into the active profile and mark it active.

    Raises the repository's ``ConfigurationError`` on an unreadable existing
    file or a credential-like value; callers show that message and keep the
    dialog open.
    """
    profile_id = active_profile_id(services)
    existing = services.profiles.get(profile_id)
    payload = dict(existing.payload) if existing is not None else {}
    payload[section] = data
    if extra:
        payload.update(extra)
    services.profiles.save(
        Profile(
            profile_id=profile_id,
            name=existing.name if existing is not None else "Default",
            created_at=existing.created_at if existing is not None else "",
            payload=payload,
        )
    )
    if services.state.snapshot().active_profile_id != profile_id:
        services.state.update(active_profile_id=profile_id)
    return profile_id


def store_profile_section_if_active(
    services: AppServices,
    section: str,
    data: dict[str, Any],
    *,
    extra: dict[str, Any] | None = None,
) -> str | None:
    """Store a section only when the operator has loaded a profile.

    Starting a video source must not create a profile as a side effect, so
    automatic bookkeeping (source choice, dry-run summary) uses this variant.
    """
    if services.state.snapshot().active_profile_id is None:
        return None
    return store_profile_section(services, section, data, extra=extra)
