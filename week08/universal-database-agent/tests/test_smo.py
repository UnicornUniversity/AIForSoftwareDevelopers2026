from __future__ import annotations

from pathlib import Path

from uda.adapters.smo import SMO_FALLBACK, detect_smo_availability


def make_gac(root: Path, version: str = "17.0.0.0") -> Path:
    directory = (
        root
        / "Microsoft.NET"
        / "assembly"
        / "GAC_MSIL"
        / "Microsoft.SqlServer.Smo"
        / f"v4.0_{version}__89845dcd8080cc91"
    )
    directory.mkdir(parents=True)
    (directory / "Microsoft.SqlServer.Smo.dll").write_bytes(b"not-a-real-assembly")
    return directory


def make_sqlps_module(root: Path, version: str = "17.0") -> Path:
    directory = (
        root
        / "Microsoft SQL Server"
        / "170"
        / "Tools"
        / "PowerShell"
        / "Modules"
        / "SQLPS"
    )
    directory.mkdir(parents=True)
    (directory / "SQLPS.psd1").write_text(
        f"@{{ ModuleVersion = '{version}' }}", encoding="utf-8"
    )
    return directory


def test_non_windows_host_reports_unavailable(tmp_path: Path) -> None:
    status = detect_smo_availability(platform="linux", search_roots=[tmp_path])
    assert status.available is False
    assert "Windows-only" in status.detail
    assert status.fallback == SMO_FALLBACK


def test_gac_detection_reports_version(tmp_path: Path) -> None:
    make_gac(tmp_path)
    status = detect_smo_availability(platform="win32", search_roots=[tmp_path])
    assert status.available is True
    assert status.version == "17.0.0.0"
    assert status.mechanism == "gac"
    assert "does not load SMO" in status.detail


def test_highest_gac_version_is_selected(tmp_path: Path) -> None:
    make_gac(tmp_path, "16.100.0.0")
    make_gac(tmp_path, "17.0.0.0")
    status = detect_smo_availability(platform="win32", search_roots=[tmp_path])
    assert status.version == "17.0.0.0"


def test_sqlserver_powershell_module_is_detected(tmp_path: Path) -> None:
    make_sqlps_module(tmp_path, "17.0")
    status = detect_smo_availability(platform="win32", search_roots=[tmp_path])
    assert status.available is True
    assert status.version == "17.0"
    assert status.mechanism == "powershell-module"


def test_unavailable_reports_actionable_fallback(tmp_path: Path) -> None:
    status = detect_smo_availability(platform="win32", search_roots=[tmp_path])
    assert status.available is False
    assert status.version is None
    assert "not found" in status.detail
    assert "SQLAlchemy Inspector" in status.fallback
    assert "does not install" in status.fallback
