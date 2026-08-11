"""Deterministic status classification for repository discovery results.

Absence becomes Not_Implemented only after a complete repository search; an
existing command with a missing named executable becomes Environment_Blocked.
"""

from __future__ import annotations

from .discovery_models import (
    DiscoveredCommand,
    DiscoveryOutcome,
    DiscoverySearchEvidence,
    ToolResolution,
)
from .model_types import AssessmentStatus

_REQUIRED_CHECKS = (
    "python-lint", "python-types", "python-tests", "python-coverage",
    "typescript-types", "typescript-tests", "typescript-coverage", "rust-check",
    "rust-tests", "engine-build", "frontend-build", "desktop-build",
)


def classify_discovery_outcomes(
    commands: tuple[DiscoveredCommand, ...],
    search_paths: tuple[str, ...],
    search_complete: bool,
    resolutions: tuple[ToolResolution, ...],
) -> tuple[DiscoveryOutcome, ...]:
    """Apply exhaustive-search and named-prerequisite status rules."""
    command_by_id = {command.check_id: command for command in commands}
    resolution_by_name = {item.name: item for item in resolutions}
    check_ids = tuple(dict.fromkeys((*_REQUIRED_CHECKS, *(item.check_id for item in commands))))
    outcomes: list[DiscoveryOutcome] = []
    search = DiscoverySearchEvidence(search_paths, search_complete)
    for check_id in check_ids:
        command = command_by_id.get(check_id)
        if command is None:
            status = AssessmentStatus.NOT_IMPLEMENTED if search_complete else AssessmentStatus.UNVERIFIED
            outcomes.append(DiscoveryOutcome(check_id, status, None, search))
            continue
        missing = tuple(
            tool
            for tool in command.required_tools
            if tool in resolution_by_name and not resolution_by_name[tool].available
        )
        status = AssessmentStatus.ENVIRONMENT_BLOCKED if missing else AssessmentStatus.UNVERIFIED
        outcomes.append(DiscoveryOutcome(check_id, status, command, search, missing))
    return tuple(outcomes)
