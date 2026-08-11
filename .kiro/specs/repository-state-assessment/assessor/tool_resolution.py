"""Resolve selected verification tools without installing or downloading them.

Resolution checks repository-local directories and every PATH entry in order,
using configured Windows PATHEXT semantics before a bounded version probe.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

from .discovery_models import ToolResolution

ExecutableLookup = Callable[[str, tuple[Path, ...]], str | None]
VersionProbe = Callable[[str, tuple[str, ...]], str | None]
_DEFAULT_PATHEXT = ".COM;.EXE;.BAT;.CMD"


def _candidate_directories(repository_root: Path) -> tuple[Path, ...]:
    """Return repository-local and user tool directories in search order."""
    directories = [
        repository_root / ".venv" / "Scripts",
        repository_root / ".venv" / "bin",
        repository_root / "apps" / "ui" / "node_modules" / ".bin",
        Path(sys.executable).parent,
    ]
    cargo_home = os.environ.get("CARGO_HOME")
    user_profile = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if cargo_home:
        directories.append(Path(cargo_home) / "bin")
    elif user_profile:
        directories.append(Path(user_profile) / ".cargo" / "bin")
    return tuple(dict.fromkeys(path.resolve() for path in directories))


def _path_directories(path_value: str, current_directory: Path) -> tuple[Path, ...]:
    """Parse PATH without discarding quoted, empty, spaced, or suffixed entries."""
    directories: list[Path] = []
    for raw_entry in path_value.split(os.pathsep):
        entry = raw_entry.strip()
        if len(entry) >= 2 and entry[0] == entry[-1] and entry[0] in {'"', "'"}:
            entry = entry[1:-1]
        directory = current_directory if not entry else Path(entry)
        directories.append(directory.resolve())
    return tuple(directories)


def _path_extensions(value: str) -> tuple[str, ...]:
    """Normalize configured PATHEXT values while retaining configured order."""
    extensions: list[str] = []
    for raw_extension in value.split(";"):
        extension = raw_extension.strip()
        if not extension:
            continue
        normalized = extension if extension.startswith(".") else f".{extension}"
        if normalized.casefold() not in {item.casefold() for item in extensions}:
            extensions.append(normalized)
    return tuple(extensions)


def _candidate_names(name: str, extensions: tuple[str, ...]) -> tuple[str, ...]:
    """Return exact and PATHEXT-appended names in Windows search order."""
    names = [name]
    if Path(name).suffix.casefold() not in {item.casefold() for item in extensions}:
        names.extend(f"{name}{extension}" for extension in extensions)
    return tuple(names)


def _case_insensitive_file(directory: Path, candidate_name: str) -> Path | None:
    """Find one file by Windows case-insensitive naming semantics."""
    candidate = directory / candidate_name
    if candidate.is_file():
        return candidate.resolve()
    try:
        for entry in directory.iterdir():
            if entry.name.casefold() == candidate_name.casefold() and entry.is_file():
                return entry.resolve()
    except OSError:
        return None
    return None


def _lookup_existing(
    name: str,
    directories: tuple[Path, ...],
    extensions: tuple[str, ...] | None = None,
) -> str | None:
    """Search every supplied directory in order using Windows name semantics."""
    configured = (
        extensions
        if extensions is not None
        else _path_extensions(os.environ.get("PATHEXT", _DEFAULT_PATHEXT))
    )
    candidate_names = _candidate_names(name, configured)
    for directory in directories:
        for candidate_name in candidate_names:
            match = _case_insensitive_file(directory, candidate_name)
            if match is not None:
                return str(match)
    return None


def _probe_version(executable: str, args: tuple[str, ...]) -> str | None:
    """Run one non-interactive version command with network proxies disabled."""
    argv: list[str]
    if Path(executable).suffix.lower() in {".cmd", ".bat"}:
        payload = subprocess.list2cmdline((executable, *args))
        argv = ["cmd.exe", "/d", "/s", "/c", payload]
    else:
        argv = [executable, *args]
    environment = os.environ.copy()
    environment.update({"NO_PROXY": "*", "no_proxy": "*"})
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    if completed.returncode != 0:
        return None
    output = (completed.stdout or completed.stderr).strip()
    return output.splitlines()[0] if output else None


class ToolResolver:
    """Resolve executable paths and versions using observation-only probes."""

    def __init__(
        self,
        repository_root: Path,
        *,
        executable_lookup: ExecutableLookup | None = None,
        version_probe: VersionProbe | None = None,
        search_path: str | None = None,
        path_extensions: str | None = None,
        current_directory: Path | None = None,
        local_directories: tuple[Path, ...] | None = None,
    ) -> None:
        """Configure complete search inputs and dependency-free probe seams."""
        self._repository_root = repository_root.resolve()
        current = (current_directory or Path.cwd()).resolve()
        inherited_path = os.environ.get("PATH", "") if search_path is None else search_path
        local = (
            _candidate_directories(self._repository_root)
            if local_directories is None
            else tuple(path.resolve() for path in local_directories)
        )
        self._directories = (*local, *_path_directories(inherited_path, current))
        extension_value = (
            os.environ.get("PATHEXT", _DEFAULT_PATHEXT)
            if path_extensions is None
            else path_extensions
        )
        self._extensions = _path_extensions(extension_value)
        self._lookup = executable_lookup
        self._probe = version_probe or _probe_version

    def resolve(self, tool_names: Iterable[str]) -> tuple[ToolResolution, ...]:
        """Resolve unique tools after an ordered, complete executable search."""
        results: list[ToolResolution] = []
        searched = tuple(str(path) for path in self._directories)
        for name in sorted(set(tool_names)):
            executable = (
                self._lookup(name, self._directories)
                if self._lookup is not None
                else _lookup_existing(name, self._directories, self._extensions)
            )
            version = self._probe(executable, ("--version",)) if executable else None
            results.append(ToolResolution(name, executable, version, searched))
        return tuple(results)
