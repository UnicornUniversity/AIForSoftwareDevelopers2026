"""On-disk profile repository: one portable JSON file per profile.

The file name is the profile id. Reads migrate older documents in memory; the
upgraded form is written the next time the profile is saved, so a read-only
operation never modifies the operator's files.

An unreadable or invalid file is skipped by :meth:`list_profiles` (with a log
line) rather than crashing the dialog. Requesting it by id raises an
application error with the file name, so the operator learns which file is
broken instead of silently losing settings.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from ...config import profiles_dir
from ...errors import ConfigurationError
from ...interfaces.profiles import PROFILE_SCHEMA_VERSION, Profile
from .profile_document import (
    atomic_write_json,
    profile_from_document,
    profile_to_document,
    read_json_document,
    validate_profile_id,
)

__all__ = ["JsonProfileRepository", "slugify_profile_name"]

_log = logging.getLogger(__name__)

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify_profile_name(name: str) -> str:
    """A safe, readable profile id derived from a display name."""
    slug = _SLUG_STRIP.sub("-", name.strip().lower()).strip("-")
    return slug[:40] or "profile"


class JsonProfileRepository:
    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else profiles_dir()

    @property
    def root(self) -> Path:
        return self._root

    # -- reads ---------------------------------------------------------------

    def list_profiles(self) -> list[Profile]:
        if not self._root.exists():
            return []
        profiles: list[Profile] = []
        for path in sorted(self._root.glob("*.json")):
            try:
                profiles.append(self._load_file(path))
            except (ConfigurationError, OSError) as exc:
                _log.warning(
                    "Skipping invalid profile file",
                    extra={
                        "context": {
                            "path": str(path),
                            "reason": getattr(exc, "user_message", str(exc)),
                        }
                    },
                )
        return sorted(profiles, key=lambda profile: (profile.name.lower(), profile.profile_id))

    def get(self, profile_id: str) -> Profile | None:
        path = self._path(profile_id)
        if not path.exists():
            return None
        return self._load_file(path)

    # -- writes --------------------------------------------------------------

    def save(self, profile: Profile) -> None:
        validate_profile_id(profile.profile_id)
        document = profile_to_document(profile)
        now = _now()
        created_at = profile.created_at
        if not created_at:
            existing = self.get(profile.profile_id)
            created_at = existing.created_at if existing is not None else now
        document["created_at"] = created_at
        document["updated_at"] = now
        try:
            atomic_write_json(self._path(profile.profile_id), document)
        except OSError as exc:
            raise ConfigurationError(
                f"Could not write profile {profile.profile_id!r}: {exc}",
                user_message=f"The profile could not be saved to '{self._root}' ({exc}).",
            ) from exc

    def delete(self, profile_id: str) -> None:
        path = self._path(profile_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ConfigurationError(
                f"Could not delete profile {profile_id!r}: {exc}",
                user_message=f"The profile file '{path.name}' could not be deleted ({exc}).",
            ) from exc

    def duplicate(self, profile_id: str, new_name: str) -> Profile:
        source = self.get(profile_id)
        if source is None:
            raise ConfigurationError(
                f"No such profile: {profile_id}",
                user_message="The selected profile no longer exists.",
            )
        if not new_name.strip():
            raise ConfigurationError(
                "New profile name must not be empty",
                user_message="Enter a name for the copy.",
            )
        clone_id = self._unique_id(new_name, avoid=profile_id)
        self.save(
            Profile(
                profile_id=clone_id,
                name=new_name.strip(),
                schema_version=PROFILE_SCHEMA_VERSION,
                payload=dict(source.payload),
            )
        )
        duplicate = self.get(clone_id)
        if duplicate is None:  # pragma: no cover - save() just wrote it
            raise AssertionError("duplicated profile vanished immediately after saving")
        return duplicate

    # -- internals -----------------------------------------------------------

    def _path(self, profile_id: str) -> Path:
        return self._root / f"{validate_profile_id(profile_id)}.json"

    def _load_file(self, path: Path) -> Profile:
        document = read_json_document(path)
        if isinstance(document, dict):
            # The repository's key is the file name; a document cannot claim a
            # different one and shadow another profile.
            document = dict(document)
            document["profile_id"] = path.stem
        return profile_from_document(document)

    def _unique_id(self, name: str, *, avoid: str | None = None) -> str:
        base = slugify_profile_name(name)
        candidate = base
        counter = 2
        while candidate == avoid or (self._root / f"{candidate}.json").exists():
            suffix = f"-{counter}"
            candidate = f"{base[: 40 - len(suffix)]}{suffix}"
            counter += 1
        return candidate


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
