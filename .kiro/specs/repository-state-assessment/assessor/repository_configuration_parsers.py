"""Small parsers for repository-owned verification configuration sources.

The parsers intentionally retain declaration line numbers and whole-file hashes;
they do not execute configuration or import build scripts.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .discovery_models import DiscoveredScenario, LockedVersion
from .execution_models import CommandSource
from .model_types import SourceLocation


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """UTF-8 repository text plus stable source identity."""

    relative_path: str
    text: str
    sha256: str

    @property
    def lines(self) -> tuple[str, ...]:
        """Return source lines without discarding empty declarations."""
        return tuple(self.text.splitlines())

    def source(self, line: int) -> CommandSource:
        """Create evidence for one inclusive declaration line."""
        return CommandSource(SourceLocation(self.relative_path, line, line), self.sha256)


def load_document(repository_root: Path, path: Path) -> SourceDocument:
    """Read one current repository source as UTF-8 with replacement."""
    data = path.read_bytes()
    relative = path.relative_to(repository_root).as_posix()
    return SourceDocument(relative, data.decode("utf-8", errors="replace"), hashlib.sha256(data).hexdigest())


def split_command(command: str) -> tuple[str, ...]:
    """Split a repository command without invoking a shell."""
    try:
        return tuple(shlex.split(command, posix=True))
    except ValueError:
        return ()


def parse_make_recipes(document: SourceDocument) -> dict[str, tuple[tuple[str, ...], CommandSource]]:
    """Parse first concrete recipe line for every Make target."""
    recipes: dict[str, tuple[tuple[str, ...], CommandSource]] = {}
    target: str | None = None
    for number, line in enumerate(document.lines, 1):
        match = re.match(r"^([A-Za-z0-9_.-]+)\s*:(?![=])", line)
        if match:
            target = match.group(1)
        elif target and line.startswith("\t") and line.strip() and not line.lstrip().startswith("#"):
            recipes.setdefault(target, (split_command(line.strip()), document.source(number)))
        elif line and not line[0].isspace():
            target = None
    return recipes


def parse_package_scripts(document: SourceDocument) -> dict[str, tuple[str, CommandSource]]:
    """Parse package scripts and retain each script key's source line."""
    payload = json.loads(document.text)
    scripts = payload.get("scripts", {})
    results: dict[str, tuple[str, CommandSource]] = {}
    for name, command in scripts.items():
        line = next(
            (number for number, text in enumerate(document.lines, 1) if f'"{name}"' in text),
            1,
        )
        results[str(name)] = (str(command), document.source(line))
    return results


def parse_workflow_commands(document: SourceDocument) -> tuple[tuple[tuple[str, ...], CommandSource], ...]:
    """Parse scalar and block YAML run commands without needing a YAML loader."""
    commands: list[tuple[tuple[str, ...], CommandSource]] = []
    lines = document.lines
    index = 0
    while index < len(lines):
        match = re.match(r"^(\s*)run:\s*(.*)$", lines[index])
        if not match:
            index += 1
            continue
        value = match.group(2).strip()
        if value and value not in {"|", ">"}:
            commands.append((split_command(value), document.source(index + 1)))
            index += 1
            continue
        base_indent = len(match.group(1))
        index += 1
        while index < len(lines):
            line = lines[index]
            if line.strip() and len(line) - len(line.lstrip()) <= base_indent:
                break
            stripped = line.strip()
            if stripped and not stripped.startswith(("#", "if ", "else", "fi", "$")):
                argv = split_command(stripped)
                if argv:
                    commands.append((argv, document.source(index + 1)))
            index += 1
    return tuple(commands)


def parse_markdown_commands(document: SourceDocument) -> tuple[tuple[tuple[str, ...], CommandSource], ...]:
    """Parse non-comment command lines inside fenced documentation blocks."""
    commands: list[tuple[tuple[str, ...], CommandSource]] = []
    in_fence = False
    for number, line in enumerate(document.lines, 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        stripped = line.strip().rstrip("\\").strip()
        if in_fence and stripped and not stripped.startswith(("#", "$", "<")):
            argv = split_command(stripped)
            if argv:
                commands.append((argv, document.source(number)))
    return tuple(commands)


def parse_tauri_targets(document: SourceDocument, host_platform: str) -> tuple[tuple[str, bool, CommandSource], ...]:
    """Read configured bundle targets and classify host applicability."""
    payload = json.loads(document.text)
    targets = payload.get("bundle", {}).get("targets", [])
    line = next(
        (number for number, text in enumerate(document.lines, 1) if '"targets"' in text),
        1,
    )
    supported = {
        "win32": {"nsis", "msi"},
        "darwin": {"dmg", "app"},
        "linux": {"deb", "appimage", "rpm"},
    }.get(host_platform, set())
    return tuple((str(target), str(target).lower() in supported, document.source(line)) for target in targets)


def parse_playwright_projects(document: SourceDocument) -> tuple[tuple[str, str], ...]:
    """Read project names and nearby testMatch expressions from Playwright config."""
    projects: list[tuple[str, str]] = []
    current: str | None = None
    for line in document.lines:
        name_match = re.search(r"\bname\s*:\s*[\"']([^\"']+)", line)
        if name_match:
            current = name_match.group(1)
        match = re.search(r"\btestMatch\s*:\s*(.+?)(?:,\s*)?$", line.strip())
        if current and match:
            projects.append((current, match.group(1)))
            current = None
    return tuple(projects)


def parse_playwright_scenarios(
    document: SourceDocument,
    projects: tuple[tuple[str, str], ...],
) -> tuple[DiscoveredScenario, ...]:
    """Inventory static Playwright test titles assigned by configured testMatch."""
    file_name = Path(document.relative_path).name
    project = next(
        (
            name
            for name, test_match in projects
            if (file_name.endswith(".media.ts")) == ("media" in test_match)
            and (file_name.endswith(".spec.ts")) == ("spec" in test_match)
        ),
        "unconfigured",
    )
    scenarios: list[DiscoveredScenario] = []
    pattern = re.compile(r"(?<!\.)\btest\s*\(\s*[\"'`]([^\"'`]+)[\"'`]")
    for number, line in enumerate(document.lines, 1):
        for match in pattern.finditer(line):
            scenarios.append(DiscoveredScenario(project, match.group(1), document.source(number)))
    return tuple(scenarios)


def _toml_locked_versions(document: SourceDocument, ecosystem: str) -> tuple[LockedVersion, ...]:
    """Parse package name/version pairs from TOML lockfiles."""
    payload: dict[str, Any] = tomllib.loads(document.text)
    packages = payload.get("package", [])
    results: list[LockedVersion] = []
    for package in packages if isinstance(packages, list) else []:
        if not isinstance(package, dict) or "name" not in package or "version" not in package:
            continue
        name = str(package["name"])
        line = next(
            (number for number, text in enumerate(document.lines, 1) if text.strip() == f'name = "{name}"'),
            1,
        )
        results.append(LockedVersion(ecosystem, name, str(package["version"]), document.source(line)))
    return tuple(results)


def parse_lock_versions(document: SourceDocument) -> tuple[LockedVersion, ...]:
    """Parse Python, Node, or Rust locked versions from the file type."""
    if document.relative_path.endswith("uv.lock"):
        return _toml_locked_versions(document, "python")
    if document.relative_path.endswith("Cargo.lock"):
        return _toml_locked_versions(document, "rust")
    if not document.relative_path.endswith("pnpm-lock.yaml"):
        return ()

    results: list[LockedVersion] = []
    pending: tuple[str, int] | None = None
    key_pattern = re.compile(r"^\s{2,}(['\"]?)([^'\":]+(?:/[^'\":]+)?)\1:\s*$")
    version_pattern = re.compile(r"^\s+version:\s*['\"]?([^'\"\s(]+)")
    for number, line in enumerate(document.lines, 1):
        key = key_pattern.match(line)
        if key:
            pending = (key.group(2), number)
            continue
        version = version_pattern.match(line)
        if pending and version:
            name, source_line = pending
            results.append(LockedVersion("node", name, version.group(1), document.source(source_line)))
            pending = None
        elif line and not line.startswith(" "):
            pending = None
    return tuple(results)
