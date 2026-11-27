"""Per-object SQL DDL extraction through SMO (``D-07``, ``Q-06``).

SMO is the approved primary native DDL mechanism. This module invokes the SMO assemblies
that are already installed on the host through PowerShell; it never installs, loads into
the UDA process, or modifies system configuration.

Provenance is explicit:

- ``server_module_definition`` for views, where SMO returns the definition stored in
  ``sys.sql_modules``;
- ``smo_scripter`` for tables, where SQL Server does not retain byte-original DDL text and
  SMO generates the current definition from live metadata.

Neither label claims to be a byte-for-byte historical source file.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from ..config import DatabaseConfig
from ..errors import ConfigurationError
from ..metadata.models import DatabaseMetadata, TableMetadata
from .smo import SmoStatus, detect_smo_availability

DDL_MECHANISM = "smo"
PROVENANCE_TABLE = "smo_scripter"
PROVENANCE_VIEW = "server_module_definition"

DdlObjectStatus = Literal["extracted", "unavailable", "failed", "unsupported"]
DdlExtractionStatus = Literal[
    "complete", "partial", "failed", "unavailable", "not_requested"
]

_SMO_ASSEMBLIES = (
    "Microsoft.SqlServer.ConnectionInfo",
    "Microsoft.SqlServer.Management.Sdk.Sfc",
    "Microsoft.SqlServer.SqlEnum",
    "Microsoft.SqlServer.Smo",
)
_PROCESS_ENV_KEYS = (
    "PATH",
    "SystemRoot",
    "WINDIR",
    "TEMP",
    "TMP",
    "PATHEXT",
    "COMSPEC",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "ProgramFiles",
    "ProgramFiles(x86)",
)
_MAX_REQUEST_CHARS = 20_000


@dataclass(frozen=True)
class DdlObject:
    physical_id: str
    kind: Literal["table", "view"]
    status: DdlObjectStatus
    ddl: str | None = None
    error: str | None = None
    provenance: str | None = None
    is_original_text: bool = False


@dataclass(frozen=True)
class DdlExtraction:
    status: DdlExtractionStatus
    mechanism: str | None
    version: str | None
    detail: str
    objects: tuple[DdlObject, ...] = ()

    @property
    def object_count(self) -> int:
        return len(self.objects)

    @property
    def extracted_count(self) -> int:
        return sum(1 for item in self.objects if item.status == "extracted")

    @property
    def available(self) -> bool:
        return self.status in {"complete", "partial"}


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


def normalize_ddl(text: str) -> str:
    """Normalize line endings and a trailing newline without rewriting SQL."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    return f"{normalized}\n" if normalized else ""


def _sanitize(text: str, secret: str = "") -> str:
    value = text.strip()
    if secret:
        value = value.replace(secret, "***")
    value = " ".join(value.split())
    return value[:500]


def _unavailable_objects(
    metadata: DatabaseMetadata, detail: str
) -> tuple[DdlObject, ...]:
    return tuple(
        DdlObject(
            physical_id=item.physical_id,
            kind=item.object_type,
            status="unavailable",
            error=detail,
        )
        for item in sorted(metadata.objects, key=lambda row: row.physical_id)
    )


def _unavailable_extraction(
    metadata: DatabaseMetadata, detail: str
) -> DdlExtraction:
    return DdlExtraction(
        status="unavailable",
        mechanism=None,
        version=None,
        detail=detail,
        objects=_unavailable_objects(metadata, detail),
    )


def _failed_extraction(
    metadata: DatabaseMetadata, detail: str
) -> DdlExtraction:
    objects = _unavailable_objects(metadata, detail)
    return DdlExtraction(
        status="failed",
        mechanism=DDL_MECHANISM,
        version=None,
        detail=detail,
        objects=tuple(
            DdlObject(
                physical_id=item.physical_id,
                kind=item.kind,
                status="failed",
                error=detail,
            )
            for item in objects
        ),
    )


def _invoke_powershell(env: Mapping[str, str], timeout: float) -> ProcessResult:
    executable = shutil.which("powershell") or shutil.which("powershell.exe")
    if executable is None:
        return ProcessResult(127, "", "PowerShell is not available on PATH.")
    encoded = base64.b64encode(_POWERSHELL_SCRIPT.encode("utf-16-le")).decode("ascii")
    try:
        completed = subprocess.run(
            [
                executable,
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                encoded,
            ],
            capture_output=True,
            env=dict(env),
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ProcessResult(
            124, "", f"PowerShell timed out after {timeout:.0f} seconds."
        )
    except OSError as exc:
        return ProcessResult(126, "", f"PowerShell could not start ({type(exc).__name__}).")
    return ProcessResult(
        completed.returncode,
        completed.stdout.decode("utf-8-sig", errors="replace"),
        completed.stderr.decode("utf-8-sig", errors="replace"),
    )


def _parse_payload(text: str) -> dict[str, object] | None:
    candidate = text.strip()
    if not candidate:
        return None
    for value in (candidate.splitlines()[-1], candidate):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


class SmoDdlExtractor:
    """Extract per-object SQL DDL using installed SMO through PowerShell."""

    def __init__(
        self,
        config: DatabaseConfig,
        *,
        smo_provider: Callable[[], SmoStatus] = detect_smo_availability,
        process_runner: Callable[[Mapping[str, str], float], ProcessResult] | None = None,
        platform: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._config = config
        self._smo_provider = smo_provider
        self._process_runner = process_runner or _invoke_powershell
        self._platform = platform if platform is not None else sys.platform
        self._timeout_seconds = timeout_seconds

    def extract(self, metadata: DatabaseMetadata) -> DdlExtraction:
        objects = sorted(metadata.objects, key=lambda item: item.physical_id)
        if not objects:
            return DdlExtraction(
                status="complete",
                mechanism=DDL_MECHANISM,
                version=None,
                detail="No tables or views require DDL extraction.",
                objects=(),
            )
        if not self._platform.startswith("win"):
            return _unavailable_extraction(
                metadata, "SMO DDL extraction requires Windows."
            )
        smo = self._smo_provider()
        if not smo.available:
            return _unavailable_extraction(
                metadata,
                "SMO is unavailable: " + smo.detail,
            )
        try:
            self._config.validate_connection_settings()
        except ConfigurationError as exc:
            return _unavailable_extraction(metadata, str(exc))

        request = {
            "objects": [
                {
                    "physical_id": item.physical_id,
                    "schema": item.schema_name,
                    "name": item.name,
                    "kind": item.object_type,
                }
                for item in objects
            ]
        }
        request_json = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        if len(request_json) > _MAX_REQUEST_CHARS:
            return _unavailable_extraction(
                metadata,
                "The SMO request is too large; extract explicit schemas with --schema.",
            )
        env = self._build_environment(request_json)
        try:
            result = self._process_runner(env, self._timeout_seconds)
        except subprocess.TimeoutExpired:
            return _failed_extraction(metadata, "SMO extraction timed out.")
        except OSError as exc:
            return _failed_extraction(
                metadata, f"SMO extraction could not start ({type(exc).__name__})."
            )

        payload = _parse_payload(result.stdout)
        if payload is None:
            detail = result.stderr or (
                f"SMO extraction returned no result (exit {result.returncode})."
            )
            return _failed_extraction(
                metadata, _sanitize(detail, self._config.password)
            )
        if payload.get("status") != "ok":
            detail = str(payload.get("detail") or "SMO extraction failed.")
            return _failed_extraction(
                metadata, _sanitize(detail, self._config.password)
            )

        raw_objects = payload.get("objects") or []
        if isinstance(raw_objects, dict):
            raw_objects = [raw_objects]
        if not isinstance(raw_objects, list):
            return _failed_extraction(metadata, "SMO returned an unexpected object list.")

        by_id: dict[str, dict[str, object]] = {}
        for item in raw_objects:
            if isinstance(item, dict) and item.get("physical_id"):
                by_id[str(item["physical_id"])] = item

        entries: list[DdlObject] = []
        for table in objects:
            item = by_id.pop(table.physical_id, None)
            entries.append(self._to_ddl_object(table, item))

        version = str(payload.get("smo_version") or smo.version or "") or None
        server_version = str(payload.get("server_version") or "") or None
        extracted = sum(1 for item in entries if item.status == "extracted")
        if extracted == len(entries):
            status: DdlExtractionStatus = "complete"
        elif extracted:
            status = "partial"
        else:
            status = "failed"
        detail = (
            f"SMO {version or 'unknown'} extracted {extracted} of {len(entries)} "
            "table/view definitions."
        )
        if server_version:
            detail += f" Server version {server_version}."
        if by_id:
            detail += f" Ignored {len(by_id)} unexpected SMO result(s)."
        return DdlExtraction(
            status=status,
            mechanism=DDL_MECHANISM,
            version=version,
            detail=detail,
            objects=tuple(entries),
        )

    def _to_ddl_object(
        self, table: TableMetadata, item: dict[str, object] | None
    ) -> DdlObject:
        if item is None:
            return DdlObject(
                physical_id=table.physical_id,
                kind=table.object_type,
                status="failed",
                error="SMO returned no result for this object.",
            )
        status = str(item.get("status") or "failed")
        if status != "extracted":
            return DdlObject(
                physical_id=table.physical_id,
                kind=table.object_type,
                status="unsupported" if status == "unsupported" else "failed",
                error=_sanitize(
                    str(item.get("error") or "SMO did not extract this object."),
                    self._config.password,
                ),
            )
        ddl = normalize_ddl(str(item.get("ddl") or ""))
        if not ddl:
            return DdlObject(
                physical_id=table.physical_id,
                kind=table.object_type,
                status="failed",
                error="SMO returned an empty definition.",
            )
        default_provenance = (
            PROVENANCE_VIEW if table.object_type == "view" else PROVENANCE_TABLE
        )
        provenance = str(item.get("provenance") or default_provenance)
        is_original = bool(item.get("is_original_text", table.object_type == "view"))
        return DdlObject(
            physical_id=table.physical_id,
            kind=table.object_type,
            status="extracted",
            ddl=ddl,
            provenance=provenance,
            is_original_text=is_original,
        )

    def _build_environment(self, request_json: str) -> dict[str, str]:
        env = {
            key: os.environ[key]
            for key in _PROCESS_ENV_KEYS
            if key in os.environ
        }
        env.update(
            {
                "UDA_SMO_SERVER": (
                    f"{self._config.host},{self._config.port}"
                    if self._config.port is not None
                    else self._config.host
                ),
                "UDA_SMO_DATABASE": self._config.name,
                "UDA_SMO_LOGIN_SECURE": (
                    "true" if self._config.trusted_connection else "false"
                ),
                "UDA_SMO_ENCRYPT": "true" if self._config.encrypt else "false",
                "UDA_SMO_TRUST_CERT": (
                    "true" if self._config.trust_server_certificate else "false"
                ),
                "UDA_SMO_CONNECT_TIMEOUT": str(
                    self._config.connection_timeout_seconds
                ),
                "UDA_SMO_REQUEST": request_json,
            }
        )
        if not self._config.trusted_connection:
            env["UDA_SMO_USERNAME"] = self._config.username
            env["UDA_SMO_PASSWORD"] = self._config.password
        return env


_POWERSHELL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false

$result = [ordered]@{
    status = 'error'
    smo_version = $null
    server_version = $null
    detail = ''
    objects = @()
}

function Load-SmoAssembly([string] $name) {
    $assemblyRoot = Join-Path (Join-Path $env:WINDIR 'Microsoft.NET') 'assembly'
    foreach ($gacName in @('GAC_MSIL', 'GAC_32', 'GAC_64')) {
        $base = Join-Path (Join-Path $assemblyRoot $gacName) $name
        if (-not (Test-Path -LiteralPath $base)) { continue }
        $bestVersion = $null
        $bestPath = $null
        foreach ($dir in Get-ChildItem -LiteralPath $base -Directory) {
            $match = [regex]::Match($dir.Name, '_(\d+\.\d+\.\d+\.\d+)__')
            if (-not $match.Success) { continue }
            $version = [version]$match.Groups[1].Value
            $candidate = Join-Path $dir.FullName ($name + '.dll')
            if (-not (Test-Path -LiteralPath $candidate)) { continue }
            if (($null -eq $bestVersion) -or ($version -gt $bestVersion)) {
                $bestVersion = $version
                $bestPath = $candidate
            }
        }
        if ($null -ne $bestPath) {
            [void][Reflection.Assembly]::LoadFrom($bestPath)
            return $bestVersion
        }
    }
    throw "SMO assembly not found: $name"
}

try {
    $smoVersion = $null
    foreach ($name in @(
        'Microsoft.SqlServer.ConnectionInfo',
        'Microsoft.SqlServer.Management.Sdk.Sfc',
        'Microsoft.SqlServer.SqlEnum',
        'Microsoft.SqlServer.Smo'
    )) {
        $version = Load-SmoAssembly $name
        if ($name -eq 'Microsoft.SqlServer.Smo') { $smoVersion = $version }
    }
    $result.smo_version = $smoVersion.ToString()

    $request = $env:UDA_SMO_REQUEST | ConvertFrom-Json
    $connection = New-Object Microsoft.SqlServer.Management.Common.ServerConnection
    $connection.ServerInstance = [string]$env:UDA_SMO_SERVER
    $connection.DatabaseName = [string]$env:UDA_SMO_DATABASE
    $connection.ConnectTimeout = [int]$env:UDA_SMO_CONNECT_TIMEOUT
    if ([string]$env:UDA_SMO_LOGIN_SECURE -eq 'true') {
        $connection.LoginSecure = $true
    } else {
        $connection.LoginSecure = $false
        $connection.Login = [string]$env:UDA_SMO_USERNAME
        $connection.Password = [string]$env:UDA_SMO_PASSWORD
    }
    try {
        $connection.EncryptConnection = ([string]$env:UDA_SMO_ENCRYPT -eq 'true')
    } catch { }
    try {
        $connection.TrustServerCertificate = ([string]$env:UDA_SMO_TRUST_CERT -eq 'true')
    } catch { }

    $server = New-Object Microsoft.SqlServer.Management.Smo.Server $connection
    $result.server_version = [string]$server.VersionString
    $database = $server.Databases[[string]$env:UDA_SMO_DATABASE]
    if ($null -eq $database) {
        throw "Database not found: $($env:UDA_SMO_DATABASE)"
    }

    $viewDefinitions = @{}
    try {
        $definitionQuery = @"
SELECT s.name AS schema_name, v.name AS view_name, m.definition AS definition
FROM sys.views AS v
JOIN sys.schemas AS s ON v.schema_id = s.schema_id
JOIN sys.sql_modules AS m ON v.object_id = m.object_id
WHERE m.definition IS NOT NULL
"@
        $definitionSet = $server.ConnectionContext.ExecuteWithResults($definitionQuery)
        foreach ($row in $definitionSet.Tables[0].Rows) {
            $key = ([string]$row.schema_name) + '.' + ([string]$row.view_name)
            $viewDefinitions[$key] = [string]$row.definition
        }
    } catch { }

    $scripter = New-Object Microsoft.SqlServer.Management.Smo.Scripter $server
    $scripter.Options.ScriptDrops = $false
    $scripter.Options.IncludeHeaders = $false
    $scripter.Options.ToFileOnly = $false
    $scripter.Options.ScriptBatchTerminator = $false
    $scripter.Options.AnsiPadding = $false
    $scripter.Options.NoCommandTerminator = $true
    $scripter.Options.DriAll = $true
    $scripter.Options.Indexes = $true
    $scripter.Options.Triggers = $true
    $scripter.Options.ExtendedProperties = $true
    $scripter.Options.WithDependencies = $false
    $scripter.Options.Permissions = $false
    $scripter.Options.ScriptOwner = $false
    $scripter.Options.ScriptData = $false
    $scripter.Options.EnforceScriptingOptions = $true
    try {
        $targetName = 'Version' + ([int]$server.VersionMajor * 10)
        $scripter.Options.TargetServerVersion = [Enum]::Parse(
            [Microsoft.SqlServer.Management.Smo.SqlServerVersion], $targetName
        )
    } catch { }

    $objects = @()
    foreach ($item in @($request.objects)) {
        $entry = [ordered]@{
            physical_id = [string]$item.physical_id
            kind = [string]$item.kind
            status = 'failed'
            ddl = $null
            error = $null
            provenance = $null
            is_original_text = $false
        }
        try {
            $schema = [string]$item.schema
            $name = [string]$item.name
            $object = $null
            if ([string]$item.kind -eq 'table') {
                $object = $database.Tables[$name, $schema]
            } elseif ([string]$item.kind -eq 'view') {
                $object = $database.Views[$name, $schema]
            } else {
                $entry.status = 'unsupported'
                $entry.error = 'Unsupported object type for DDL extraction.'
            }
            if ($null -ne $object) {
                $definitionKey = $schema + '.' + $name
                $isView = [string]$item.kind -eq 'view'
                $hasDefinition = $viewDefinitions.ContainsKey($definitionKey)
                if ($isView -and $hasDefinition) {
                    $entry.status = 'extracted'
                    $entry.ddl = $viewDefinitions[$definitionKey]
                    $entry.provenance = 'server_module_definition'
                    $entry.is_original_text = $true
                } else {
                    $lines = @($scripter.Script($object))
                    if ($lines.Count -eq 0) {
                        $entry.error = 'SMO returned an empty definition.'
                    } else {
                        $entry.status = 'extracted'
                        $entry.ddl = ($lines -join "`n")
                        $entry.provenance = 'smo_scripter'
                        $entry.is_original_text = $false
                    }
                }
            } elseif ($entry.status -ne 'unsupported') {
                $entry.error = 'Object not found by SMO.'
            }
        } catch {
            $entry.error = ('SMO scripting failed: ' + $_.Exception.Message)
        }
        $objects += [pscustomobject]$entry
    }
    $result.status = 'ok'
    $result.objects = @($objects)
} catch {
    $result.status = 'error'
    $result.detail = ('SMO extraction failed: ' + $_.Exception.Message)
}

[Console]::Out.Write(($result | ConvertTo-Json -Depth 10 -Compress))
"""
