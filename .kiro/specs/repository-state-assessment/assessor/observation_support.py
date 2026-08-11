"""Sanitized artifact and workspace-only tool helpers for observation runs."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path

from .discovery_models import RepositoryDiscoveryReport, ToolResolution
from .mirror_workspace import MirrorCopyResult

MIRROR_EXCLUDED_PREFIXES = (
    ".git", ".venv", "node_modules", "apps/ui/node_modules", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "build", "dist", "apps/ui/dist",
    "apps/ui/src-tauri/target",
    ".kiro/specs/repository-state-assessment/assessment-output",
)
_SAFE_VERSION_ENV = {
    "comspec", "path", "pathext", "systemdrive", "systemroot", "temp", "tmp",
    "windir",
}


def resolve_workspace_tools(root: Path, names: tuple[str, ...]) -> tuple[ToolResolution, ...]:
    """Resolve tools through the complete local and inherited PATH search."""
    from .tool_resolution import ToolResolver

    return ToolResolver(root).resolve(names)


def _probe_version(executable: str) -> str | None:
    """Query an existing executable with a secret-free bounded environment."""
    environment = {
        name: value for name, value in os.environ.items()
        if name.casefold() in _SAFE_VERSION_ENV and value
    }
    environment.update({
        "NO_PROXY": "*", "no_proxy": "*", "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    argv = (executable, "--version")
    if Path(executable).suffix.casefold() in {".cmd", ".bat"}:
        argv = ("cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline(argv))
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=10, env=environment,
            stdin=subprocess.DEVNULL, check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0] if output else None


def repository_search_paths(report: RepositoryDiscoveryReport) -> tuple[str, ...]:
    """Return the exact configuration sources searched for commands."""
    return tuple(sorted({
        source.location.path
        for command in report.commands
        for source in command.sources
    }))


def build_omissions(
    report: RepositoryDiscoveryReport,
    mirror: MirrorCopyResult | None,
    *,
    mirror_execution_admitted: bool = False,
) -> tuple[dict[str, object], ...]:
    """Record every deferred, unsafe, unavailable, or excluded operation."""
    unresolved = {item.name for item in report.tool_resolutions if not item.available}
    records: list[dict[str, object]] = []
    for outcome in report.outcomes:
        command = outcome.command
        missing = (
            tuple(tool for tool in command.required_tools if tool in unresolved)
            if command else ()
        )
        if command is None:
            reason = "no command found after the complete bounded repository configuration search"
        elif missing:
            reason = (
                "observation-only phase limit; prerequisite unresolved in "
                f"workspace-only search: {', '.join(missing)}"
            )
        else:
            reason = "observation-only phase limit stops before repository process execution"
        records.append({
            "operation_id": outcome.check_id,
            "command_or_procedure": list(command.argv) if command else [],
            "affected_content": [],
            "reason": reason,
            "dependent_checks": [
                {"check_id": outcome.check_id, "status": outcome.status.value}
            ],
        })
    if not mirror_execution_admitted:
        records.append({
            "operation_id": "mirror-process-execution", "command_or_procedure": [],
            "affected_content": [],
            "reason": "no discovered command has enforceable process-local loopback containment",
            "dependent_checks": [
                {"check_id": item.check_id, "status": "Unverified"}
                for item in report.outcomes
            ],
        })
    records.extend((
        {
            "operation_id": "dependency-install-or-download", "command_or_procedure": [],
            "affected_content": [], "reason": "installs and downloads are prohibited",
            "dependent_checks": [],
        },
        {
            "operation_id": "external-provider-or-credential-use",
            "command_or_procedure": [], "affected_content": [],
            "reason": "provider calls and credential access are prohibited",
            "dependent_checks": [],
        },
        {
            "operation_id": "destructive-git-or-production-repair",
            "command_or_procedure": [], "affected_content": [],
            "reason": "source mutation, destructive Git, commit, push, and production repair are prohibited",
            "dependent_checks": [],
        },
    ))
    if mirror:
        records.extend({
            "operation_id": f"mirror-exclusion:{path}",
            "command_or_procedure": ["copy", path], "affected_content": [],
            "reason": "excluded by recorded mirror policy", "dependent_checks": [],
        } for path in mirror.excluded_paths)
    return tuple(records)


def write_json(root: Path, relative: str, value: object) -> Path:
    """Exclusively write canonical sanitized metadata below the output root."""
    target = (root / relative).resolve(strict=False)
    if not target.is_relative_to(root):
        raise ValueError("artifact path escapes output root")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(_json_value(value), stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return target


def _json_value(value: object) -> object:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value
