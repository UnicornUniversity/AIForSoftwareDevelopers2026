"""The on-disk profile document: validation, migration and safety checks.

A profile file is plain JSON, meant to be copied between machines and read by a
human. Two rules protect that promise:

* the document carries an explicit ``schema_version`` and older documents are
  migrated on read;
* credential-like keys are refused on load and on save, because a portable
  profile is exactly the kind of file that ends up in a shared folder.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...errors import ConfigurationError
from ...interfaces.profiles import PROFILE_SCHEMA_VERSION, Profile

__all__ = [
    "atomic_write_json",
    "find_secret_paths",
    "migrate_profile_document",
    "profile_from_document",
    "profile_to_document",
    "read_json_document",
    "validate_profile_id",
]

_IDENTITY_KEYS = frozenset(
    {"schema_version", "profile_id", "name", "created_at", "updated_at", "payload"}
)

_SECRET_KEYWORDS = (
    "password",
    "passwd",
    "secret",
    "token",
    "apikey",
    "accesskey",
    "privatekey",
    "credential",
    "authorization",
    "bearer",
)

_RESERVED_WINDOWS_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)

_MAX_PROFILE_ID = 64


def validate_profile_id(profile_id: str) -> str:
    """Return the id if it is safe to use as a file name, else raise.

    Profiles are stored as ``<id>.json``; accepting ``..`` or a backslash would
    turn a save into an arbitrary file write.
    """
    if not isinstance(profile_id, str) or not profile_id:
        raise ConfigurationError(
            "Profile id must not be empty",
            user_message="The profile id is missing.",
        )
    if len(profile_id) > _MAX_PROFILE_ID:
        raise ConfigurationError(
            f"Profile id is too long: {profile_id!r}",
            user_message="The profile id is too long.",
        )
    if not profile_id[0].isalnum() or not all(
        character.isalnum() or character in "-_" for character in profile_id
    ):
        raise ConfigurationError(
            f"Profile id contains unsupported characters: {profile_id!r}",
            user_message=(
                "Profile ids may contain only letters, digits, hyphens and underscores."
            ),
        )
    if profile_id.lower() in _RESERVED_WINDOWS_NAMES:
        raise ConfigurationError(
            f"Profile id is a reserved file name: {profile_id!r}",
            user_message=f"'{profile_id}' is a reserved file name on Windows.",
        )
    return profile_id


def find_secret_paths(value: object, *, prefix: str = "") -> list[str]:
    """Dotted paths of any credential-like key anywhere in ``value``."""
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            normalised = "".join(character for character in str(key).lower() if character.isalnum())
            if any(keyword in normalised for keyword in _SECRET_KEYWORDS):
                found.append(path)
            found.extend(find_secret_paths(child, prefix=path))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found.extend(find_secret_paths(child, prefix=f"{prefix}[{index}]"))
    return found


def _refuse_secrets(payload: Mapping[str, Any]) -> None:
    secrets = find_secret_paths(payload)
    if secrets:
        joined = ", ".join(secrets[:5])
        raise ConfigurationError(
            f"Profile contains credential-like fields: {joined}",
            user_message=(
                f"This profile contains credential-like field(s): {joined}. "
                "Profiles are portable JSON and must never store secrets. "
                "Keep API keys in the environment instead."
            ),
        )


# -- migration ---------------------------------------------------------------


def migrate_profile_document(document: object) -> dict[str, Any]:
    """Bring any readable profile document up to the current schema version.

    Version 0 is the legacy, unversioned form where settings lived at the top
    level. It is wrapped into ``payload`` here rather than rejected, so a
    classroom machine that predates versioning still opens its profiles.
    """
    if not isinstance(document, dict):
        raise ConfigurationError(
            "Profile document must be a JSON object",
            user_message="The profile file is not a JSON object and cannot be read.",
        )

    version = document.get("schema_version", 0)
    if isinstance(version, bool) or not isinstance(version, int):
        raise ConfigurationError(
            f"Profile schema version must be an integer, got {version!r}",
            user_message="The profile file has an invalid schema version.",
        )
    if version > PROFILE_SCHEMA_VERSION:
        raise ConfigurationError(
            f"Profile schema version {version} is newer than {PROFILE_SCHEMA_VERSION}",
            user_message=(
                f"This profile was written by a newer build (schema version {version}). "
                "Update the application to open it."
            ),
        )

    migrated = dict(document)
    while version < PROFILE_SCHEMA_VERSION:
        migrated = _migrate_one_step(migrated, version)
        version = migrated["schema_version"]
    return migrated


def _migrate_one_step(document: dict[str, Any], version: int) -> dict[str, Any]:
    if version == 0:
        return _migrate_v0_to_v1(document)
    raise ConfigurationError(
        f"No migration path from profile schema version {version}",
        user_message=f"Profile schema version {version} cannot be upgraded by this build.",
    )


def _migrate_v0_to_v1(document: dict[str, Any]) -> dict[str, Any]:
    """Wrap a legacy flat document's settings into ``payload``."""
    payload: dict[str, Any] = {}
    existing_payload = document.get("payload")
    if isinstance(existing_payload, dict):
        payload.update(existing_payload)
    for key, value in document.items():
        if key not in _IDENTITY_KEYS:
            payload[key] = value
    migrated = dict(document)
    migrated["schema_version"] = 1
    migrated["payload"] = payload
    return migrated


# -- conversion --------------------------------------------------------------


def profile_from_document(document: object) -> Profile:
    """Validate a migrated document and build a :class:`Profile`."""
    migrated = migrate_profile_document(document)
    if not isinstance(migrated, dict):
        raise AssertionError("migrate_profile_document always returns a dict")

    profile_id = validate_profile_id(migrated.get("profile_id", ""))
    name = migrated.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigurationError(
            f"Profile {profile_id!r} has no name",
            user_message=f"Profile '{profile_id}' has no name and cannot be loaded.",
        )
    payload = migrated.get("payload", {})
    if not isinstance(payload, dict):
        raise ConfigurationError(
            f"Profile {profile_id!r} payload is not an object",
            user_message=f"Profile '{name}' is malformed (its settings are not an object).",
        )
    _refuse_secrets(payload)

    schema_version = migrated.get("schema_version", PROFILE_SCHEMA_VERSION)
    if schema_version != PROFILE_SCHEMA_VERSION:
        raise ConfigurationError(
            f"Profile {profile_id!r} did not migrate to the current schema",
            user_message=f"Profile '{name}' could not be upgraded to the current format.",
        )

    return Profile(
        profile_id=profile_id,
        name=name.strip(),
        schema_version=schema_version,
        created_at=_timestamp(migrated.get("created_at")),
        updated_at=_timestamp(migrated.get("updated_at")),
        payload=dict(payload),
    )


def profile_to_document(profile: Profile) -> dict[str, Any]:
    """Serialise a profile, refusing anything that would make the file unsafe."""
    validate_profile_id(profile.profile_id)
    if profile.schema_version != PROFILE_SCHEMA_VERSION:
        raise ConfigurationError(
            f"Unsupported profile schema version {profile.schema_version}",
            user_message=(
                f"Profile '{profile.name}' uses schema version {profile.schema_version}, "
                "which this build cannot write."
            ),
        )
    if not profile.name.strip():
        raise ConfigurationError(
            "Profile name must not be empty",
            user_message="Give the profile a name before saving it.",
        )
    payload = dict(profile.payload)
    _refuse_secrets(payload)
    try:
        json.dumps(payload)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"Profile payload is not JSON serialisable: {exc}",
            user_message=(
                "The profile contains a value that cannot be stored as JSON "
                "(for example a NumPy array). Only plain numbers, strings, "
                "booleans, lists and objects can be saved."
            ),
        ) from exc

    return {
        "schema_version": profile.schema_version,
        "profile_id": profile.profile_id,
        "name": profile.name.strip(),
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
        "payload": payload,
    }


def _timestamp(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigurationError(
            f"Profile timestamp is not a string: {value!r}",
            user_message="The profile contains an invalid timestamp.",
        )
    return value


# -- file helpers ------------------------------------------------------------


def read_json_document(path: Path) -> object:
    """Read and parse a JSON file, mapping every failure to a friendly error."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise ConfigurationError(
            f"Could not read {path}: {exc}",
            user_message=f"The file '{path}' could not be read ({exc.strerror}).",
        ) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"{path} is not valid JSON: {exc}",
            user_message=(
                f"The file '{path.name}' is not valid JSON (line {exc.lineno}). "
                "It was left untouched."
            ),
        ) from exc


def atomic_write_json(path: Path, document: Mapping[str, Any]) -> None:
    """Write JSON via a temporary file and ``os.replace``.

    A crash mid-write therefore leaves the previous file intact instead of a
    truncated profile.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp"
    )
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
