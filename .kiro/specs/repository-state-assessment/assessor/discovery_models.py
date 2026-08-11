"""Immutable records produced by repository verification discovery.

These records retain source hashes and exhaustive-search evidence so later phases
never substitute remembered commands for the repository's current declarations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .execution_models import CommandSource
from .model_types import AssessmentStatus


@dataclass(frozen=True, slots=True)
class DiscoveredCommand:
    """One repository-derived command and every source that supports it."""

    check_id: str
    argv: tuple[str, ...]
    cwd: str
    sources: tuple[CommandSource, ...]
    required_tools: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DiscoveredScenario:
    """A configured Playwright test with its exact title and source evidence."""

    project: str
    title: str
    source: CommandSource


@dataclass(frozen=True, slots=True)
class DiscoveredTarget:
    """A Tauri bundle target and whether it applies to the selected host."""

    name: str
    host_supported: bool
    source: CommandSource


@dataclass(frozen=True, slots=True)
class LockedVersion:
    """A package version read from a current lockfile."""

    ecosystem: str
    name: str
    version: str
    source: CommandSource


class ToolResolutionStatus(StrEnum):
    """Terminal state of one complete executable and version search."""

    RESOLVED = "RESOLVED"
    RESOLVED_VERSION_UNKNOWN = "RESOLVED_VERSION_UNKNOWN"
    MISSING_AFTER_COMPLETE_SEARCH = "MISSING_AFTER_COMPLETE_SEARCH"


@dataclass(frozen=True, slots=True)
class ToolResolution:
    """Executable-path and version evidence gathered without installation."""

    name: str
    executable_path: str | None
    version: str | None
    searched_paths: tuple[str, ...]
    status: ToolResolutionStatus = field(init=False)

    def __post_init__(self) -> None:
        """Derive one non-collapsible terminal state from path and version data."""
        if self.executable_path is None:
            status = ToolResolutionStatus.MISSING_AFTER_COMPLETE_SEARCH
        elif self.version is None:
            status = ToolResolutionStatus.RESOLVED_VERSION_UNKNOWN
        else:
            status = ToolResolutionStatus.RESOLVED
        object.__setattr__(self, "status", status)

    @property
    def available(self) -> bool:
        """Return whether the complete search found an executable path."""
        return self.status is not ToolResolutionStatus.MISSING_AFTER_COMPLETE_SEARCH


@dataclass(frozen=True, slots=True)
class DiscoverySearchEvidence:
    """The bounded repository scope searched for an executable path."""

    searched_paths: tuple[str, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class DiscoveryOutcome:
    """Discovery-only status for one required verification scope."""

    check_id: str
    status: AssessmentStatus
    command: DiscoveredCommand | None
    search: DiscoverySearchEvidence
    missing_prerequisites: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepositoryDiscoveryReport:
    """Complete command, scenario, target, lock, tool, and search inventory."""

    commands: tuple[DiscoveredCommand, ...]
    scenarios: tuple[DiscoveredScenario, ...]
    targets: tuple[DiscoveredTarget, ...]
    locked_versions: tuple[LockedVersion, ...]
    tool_resolutions: tuple[ToolResolution, ...]
    outcomes: tuple[DiscoveryOutcome, ...]
