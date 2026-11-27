"""SMO availability detection (``Q-06``, ``R-13``).

SMO is the approved primary source for *original* DDL, but it is a Windows/.NET
dependency. The application never installs it, never imports it, and never makes the
SQLAlchemy Inspector path depend on it. This module only answers whether SMO assemblies
are present on the host, and states the fallback that remains available.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

SMO_FALLBACK = (
    "UDA continues with the SQLAlchemy Inspector plus SQL Server catalog queries; "
    "original DDL extraction is unavailable. To enable SMO, install SQL Server "
    "Management Objects (for example the SqlServer PowerShell module or the SQL Server "
    "SDK). UDA does not install or load it automatically."
)

_VERSION_IN_GAC_DIRECTORY = re.compile(r"_(\d+\.\d+\.\d+\.\d+)__")
_MODULE_VERSION = re.compile(r"ModuleVersion\s*=\s*['\"]([^'\"]+)['\"]")


@dataclass(frozen=True)
class SmoStatus:
    available: bool
    version: str | None = None
    mechanism: str | None = None
    detail: str = ""
    fallback: str = SMO_FALLBACK


def _version_key(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    parts: list[int] = []
    for part in value.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            return ()
    return tuple(parts)


def _module_version(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _MODULE_VERSION.search(text)
    return match.group(1) if match else None


def _gac_status(assembly_root: Path) -> SmoStatus | None:
    found: list[tuple[tuple[int, ...], str, Path]] = []
    for gac_name in ("GAC_MSIL", "GAC_32", "GAC_64"):
        base = assembly_root / gac_name / "Microsoft.SqlServer.Smo"
        if not base.is_dir():
            continue
        for version_directory in sorted(base.iterdir()):
            assembly = version_directory / "Microsoft.SqlServer.Smo.dll"
            if not version_directory.is_dir() or not assembly.is_file():
                continue
            match = _VERSION_IN_GAC_DIRECTORY.search(version_directory.name)
            version = match.group(1) if match else None
            found.append((_version_key(version), version or "", version_directory))
    if not found:
        return None
    _key, version, _path = max(found, key=lambda item: item[0])
    return SmoStatus(
        available=True,
        version=version or None,
        mechanism="gac",
        detail=(
            "SMO assembly detected in the .NET Global Assembly Cache"
            + (f" (version {version})" if version else "")
            + ". UDA detects but does not load SMO in this phase."
        ),
    )


def _module_statuses(roots: Sequence[Path]) -> list[SmoStatus]:
    statuses: list[SmoStatus] = []
    patterns = (
        "Microsoft SQL Server/*/Tools/PowerShell/Modules/SQLPS/SQLPS.psd1",
        "Microsoft SQL Server/*/Tools/PowerShell/Modules/SqlServer/*/SqlServer.psd1",
        "WindowsPowerShell/Modules/SqlServer/*/SqlServer.psd1",
        "Documents/WindowsPowerShell/Modules/SqlServer/*/SqlServer.psd1",
    )
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in patterns:
            for module_file in sorted(root.glob(pattern)):
                if not module_file.is_file():
                    continue
                version = _module_version(module_file)
                statuses.append(
                    SmoStatus(
                        available=True,
                        version=version,
                        mechanism="powershell-module",
                        detail=(
                            "SQL Server PowerShell module detected"
                            + (f" (version {version})" if version else "")
                            + "; the module provides SMO assemblies. UDA detects but does "
                            "not load it in this phase."
                        ),
                    )
                )
    return statuses


def _default_search_roots(environ: Mapping[str, str]) -> tuple[Path, ...]:
    roots: list[Path] = []
    for name in ("WINDIR", "SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "USERPROFILE"):
        value = environ.get(name)
        if value and Path(value) not in roots:
            roots.append(Path(value))
    return tuple(roots)


def detect_smo_availability(
    *,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    search_roots: Sequence[Path] | None = None,
) -> SmoStatus:
    """Return whether SMO assemblies or the SQL Server PowerShell module are present."""

    host_platform = platform if platform is not None else sys.platform
    if not host_platform.startswith("win"):
        return SmoStatus(
            available=False,
            detail=(
                "SMO is a Windows-only .NET dependency; this host is not Windows."
            ),
        )
    environment = os.environ if environ is None else environ
    roots = (
        tuple(Path(item) for item in search_roots)
        if search_roots is not None
        else _default_search_roots(environment)
    )
    if not roots:
        return SmoStatus(
            available=False,
            detail=(
                "No Windows installation roots were available to search for SMO."
            ),
        )

    candidates: list[SmoStatus] = []
    for root in roots:
        gac_status = _gac_status(root / "Microsoft.NET" / "assembly")
        if gac_status is not None:
            candidates.append(gac_status)
    candidates.extend(_module_statuses(roots))
    if not candidates:
        return SmoStatus(
            available=False,
            detail=(
                "SMO assemblies and the SQL Server PowerShell module were not found."
            ),
        )
    return max(candidates, key=lambda item: _version_key(item.version))
