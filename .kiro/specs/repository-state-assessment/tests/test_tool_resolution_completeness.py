"""Boundary tests for complete, Windows-compatible executable resolution."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from assessor.discovery_models import ToolResolutionStatus
from assessor.tool_resolution import ToolResolver, _probe_version


def _resolver(
    root: Path,
    path_value: str,
    *,
    current_directory: Path | None = None,
) -> ToolResolver:
    """Create a hermetic resolver over synthetic PATH directories."""
    return ToolResolver(
        root,
        search_path=path_value,
        path_extensions=".COM;.EXE;.BAT;.CMD;.PS1",
        current_directory=current_directory or root,
        local_directories=(),
        version_probe=lambda _path, _args: "tool 1.2.3",
    )


def _touch(path: Path) -> Path:
    """Create one synthetic executable candidate and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("synthetic", encoding="utf-8")
    return path.resolve()


def test_extensionless_pnpm_is_found_with_configured_pathext(tmp_path: Path) -> None:
    """An extensionless package shim remains a real PATHEXT-era PATH hit."""
    bin_dir = tmp_path / "bin"
    expected = _touch(bin_dir / "pnpm")

    result = _resolver(tmp_path, str(bin_dir)).resolve(("pnpm",))[0]

    assert result.executable_path == str(expected)
    assert result.version == "tool 1.2.3"
    assert result.status is ToolResolutionStatus.RESOLVED
    assert result.searched_paths == (str(bin_dir.resolve()),)


def test_path_entry_edge_cases_are_searched_exactly(tmp_path: Path) -> None:
    """Spaces, quotes, empty entries, and trailing separators retain meaning."""
    spaced = tmp_path / "tools with spaces"
    current = tmp_path / "current"
    trailing = tmp_path / "trailing"
    quoted_hit = _touch(spaced / "quoted.CMD")
    empty_hit = _touch(current / "empty.EXE")
    trailing_hit = _touch(trailing / "trailing.BAT")
    path_value = os.pathsep.join((f'"{spaced}"', "", f"{trailing}{os.sep}"))
    resolver = _resolver(tmp_path, path_value, current_directory=current)

    results = {item.name: item for item in resolver.resolve(("quoted", "empty", "trailing"))}

    assert results["quoted"].executable_path == str(quoted_hit)
    assert results["empty"].executable_path == str(empty_hit)
    assert results["trailing"].executable_path == str(trailing_hit)
    assert results["empty"].searched_paths == (
        str(spaced.resolve()),
        str(current.resolve()),
        str(trailing.resolve()),
    )


def test_first_path_match_wins(tmp_path: Path) -> None:
    """The earliest PATH directory wins when names are duplicated."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    expected = _touch(first / "same.EXE")
    _touch(second / "same.EXE")

    result = _resolver(tmp_path, os.pathsep.join((str(first), str(second)))).resolve(("same",))[0]

    assert result.executable_path == str(expected)
    assert result.status is ToolResolutionStatus.RESOLVED


def test_absent_name_is_missing_only_after_every_path_entry(tmp_path: Path) -> None:
    """A miss records every searched directory and the terminal missing state."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    result = _resolver(tmp_path, os.pathsep.join((str(first), str(second)))).resolve(("absent",))[0]

    assert result.executable_path is None
    assert result.version is None
    assert result.status is ToolResolutionStatus.MISSING_AFTER_COMPLETE_SEARCH
    assert result.searched_paths == (str(first.resolve()), str(second.resolve()))
    assert result.available is False


def test_nonzero_version_probe_preserves_resolved_path_with_unknown_version(
    tmp_path: Path,
) -> None:
    """Failed version output cannot become a version or erase path resolution."""
    bin_dir = tmp_path / "bin"
    expected = _touch(bin_dir / "broken.EXE")
    probe = tmp_path / "failed_probe.py"
    probe.write_text("print('fabricated 9.9.9')\nraise SystemExit(7)\n", encoding="utf-8")
    resolver = ToolResolver(
        tmp_path,
        search_path=str(bin_dir),
        path_extensions=".EXE",
        current_directory=tmp_path,
        local_directories=(),
        version_probe=lambda _path, _args: _probe_version(sys.executable, (str(probe),)),
    )

    result = resolver.resolve(("broken",))[0]

    assert result.executable_path == str(expected)
    assert result.version is None
    assert result.status is ToolResolutionStatus.RESOLVED_VERSION_UNKNOWN
    assert result.available is True


def test_windows_name_matching_is_case_insensitive(tmp_path: Path) -> None:
    """Executable base names and PATHEXT suffixes match without case sensitivity."""
    bin_dir = tmp_path / "bin"
    expected = _touch(bin_dir / "MiXeD.CmD")

    result = _resolver(tmp_path, str(bin_dir)).resolve(("mixed",))[0]

    assert result.executable_path == str(expected)
    assert result.status is ToolResolutionStatus.RESOLVED
