"""Record the versions of selected assessment tools without changing host state.

This is the tool-inventory stage of baseline collection: each probe runs only the
tool's own side-effect-free version argv, and a tool that cannot be started is recorded
as unavailable rather than aborting the baseline.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .baseline_models import ToolVersion


@dataclass(frozen=True, slots=True)
class ToolProbe:
    """One selected assessment tool and its side-effect-free version argv."""

    name: str
    argv: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.argv or any(not arg for arg in self.argv):
            raise ValueError("tool probe requires a name and non-empty argv")


def probe_tool_versions(probes: Sequence[ToolProbe], root: Path) -> tuple[ToolVersion, ...]:
    """Probe each distinct tool once, keeping the first probe for a repeated name."""
    versions: list[ToolVersion] = []
    observed_names: set[str] = set()
    for probe in probes:
        normalized_name = probe.name.casefold()
        if normalized_name in observed_names:
            continue
        observed_names.add(normalized_name)
        versions.append(_probe_tool(probe, root))
    return tuple(versions)


def _probe_tool(probe: ToolProbe, root: Path) -> ToolVersion:
    executable = shutil.which(probe.argv[0]) or str(Path(probe.argv[0]).resolve())
    try:
        result = subprocess.run(
            probe.argv,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        reported = (result.stdout + result.stderr).splitlines()
        lines = tuple(line.strip() for line in reported if line.strip())
        version = lines[0] if lines else f"unavailable (exit {result.returncode})"
    except (OSError, subprocess.SubprocessError) as error:
        version = f"unavailable ({type(error).__name__})"
    return ToolVersion(probe.name, version, executable)
