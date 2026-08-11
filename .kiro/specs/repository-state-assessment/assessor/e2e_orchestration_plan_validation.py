"""Fail-closed admission and path checks for one Local E2E orchestration plan.

Every check here runs before any process is created, so an unadmitted scenario, a
non-loopback network policy, a working directory outside the execution mirror, or a
redirected browser executable is refused rather than started. It sits between plan
construction and process orchestration.
"""

from __future__ import annotations

from pathlib import Path

from .contained_process_environment import require_terminating_command
from .e2e_orchestration_models import E2EOrchestrationPlan
from .e2e_partition import E2EDisposition
from .model_types import NetworkMode


def validate_plan(plan: E2EOrchestrationPlan) -> tuple[Path, Path, Path]:
    """Return the real temporary root, mirror root, and browser executable.

    Raises ``ValueError`` when the scenario is not admitted, lacks loopback-only
    network admission, or when any path escapes the mirror or is redirected.
    """
    decision = next(
        (
            item
            for item in plan.admission.partition.decisions
            if item.scenario.scenario_id == plan.scenario_id
        ),
        None,
    )
    if (
        not plan.admission.launch_admitted
        or decision is None
        or decision.disposition is not E2EDisposition.EXECUTED
    ):
        raise ValueError("Local E2E scenario is not admitted for execution")
    if (
        decision.scenario.network_policy.mode is not NetworkMode.LOOPBACK_ONLY
        or decision.scenario.network_policy.permits_non_loopback
    ):
        raise ValueError("Local E2E scenario lacks loopback-only network admission")

    temporary_root = real_directory(plan.temporary_root, "temporary root")
    mirror_root = real_directory(plan.mirror_root, "mirror root")
    if not mirror_root.is_relative_to(temporary_root):
        raise ValueError("execution mirror escapes the temporary root")
    for command in (plan.frontend, plan.engine, plan.browser):
        require_terminating_command(command)  # type: ignore[arg-type]
        cwd = real_directory(Path(command.cwd), "E2E command working directory")
        if not cwd.is_relative_to(mirror_root):
            raise ValueError("E2E command working directory escapes the mirror")
    browser = Path(plan.configured_browser_executable_path)
    if browser.is_symlink():
        raise ValueError("configured browser executable must not be a symbolic link")
    try:
        browser = browser.resolve(strict=True)
    except OSError as error:
        raise ValueError("configured browser executable is unavailable") from error
    if not browser.is_file() or not browser.is_relative_to(mirror_root):
        raise ValueError("configured browser executable must be a file in the mirror")
    return temporary_root, mirror_root, browser


def real_directory(path: Path, label: str) -> Path:
    """Resolve one existing directory without accepting symbolic redirection."""
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symbolic link")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"{label} is unavailable") from error
    if not resolved.is_dir():
        raise ValueError(f"{label} must be a directory")
    return resolved
