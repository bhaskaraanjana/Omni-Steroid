"""Fail-closed Playwright preflight admission without process launch.

Explicit observations are projected into the four required E2E dispositions.
Security invariant: ambiguity blocks launch, and cleanup that can kill a process
by occupied port rather than assessment ownership is never invoked.
"""

from __future__ import annotations

from dataclasses import dataclass

from .e2e_partition import (
    E2EPartition,
    E2EScenario,
    LocalPrerequisite,
    partition_e2e_scenarios,
)
from .model_types import NetworkMode, NetworkPolicy
from .playwright_scenario_inventory import PlaywrightScenarioInventory


@dataclass(frozen=True, slots=True)
class LoopbackPortObservation:
    """A non-mutating preflight observation for one required loopback port."""

    host: str
    port: int
    listener_pid: int | None = None
    bind_available: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("loopback port must be between 1 and 65535")
        if self.listener_pid is not None and self.listener_pid <= 0:
            raise ValueError("listener PID must be positive")


@dataclass(frozen=True, slots=True)
class PlaywrightPreflightObservation:
    """All local prerequisites that must be confirmed before any launch."""

    production_frontend_path: str | None
    production_frontend_available: bool
    frontend_startup_is_production: bool
    production_engine_path: str | None
    production_engine_available: bool
    engine_startup_is_production: bool
    browser_executable_path: str | None
    browser_available: bool
    local_test_data_available: bool
    local_services_available: bool
    loopback_ports: tuple[LoopbackPortObservation, ...]
    write_containment_established: bool
    non_loopback_denial_enforceable: bool
    unsafe_harness_cleanup_disabled: bool


@dataclass(frozen=True, slots=True)
class PlaywrightAdmissionResult:
    """Scenario dispositions and launch/cleanup permissions from one preflight."""

    inventory: PlaywrightScenarioInventory
    partition: E2EPartition
    launch_admitted: bool
    may_invoke_repository_harness_cleanup: bool


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _preflight_prerequisites(
    inventory: PlaywrightScenarioInventory,
    observation: PlaywrightPreflightObservation,
) -> tuple[LocalPrerequisite, ...]:
    prerequisites = [
        LocalPrerequisite(
            "production frontend build path",
            bool(observation.production_frontend_path) and observation.production_frontend_available,
        ),
        LocalPrerequisite(
            "production frontend startup path",
            inventory.frontend_startup_is_production and observation.frontend_startup_is_production,
        ),
        LocalPrerequisite(
            "production Python engine path",
            bool(observation.production_engine_path) and observation.production_engine_available,
        ),
        LocalPrerequisite(
            "production Python engine startup path",
            inventory.engine_startup_is_production and observation.engine_startup_is_production,
        ),
        LocalPrerequisite(
            "Playwright-configured browser executable",
            bool(observation.browser_executable_path) and observation.browser_available,
        ),
        LocalPrerequisite("required local test data", observation.local_test_data_available),
        LocalPrerequisite("required local services", observation.local_services_available),
        LocalPrerequisite("write containment", observation.write_containment_established),
        LocalPrerequisite(
            "enforceable non-loopback denial",
            observation.non_loopback_denial_enforceable,
        ),
        LocalPrerequisite(
            "ownership-safe harness cleanup",
            not inventory.harness_cleanup_kills_by_port
            or observation.unsafe_harness_cleanup_disabled,
        ),
    ]
    by_port = {item.port: item for item in observation.loopback_ports}
    for port in inventory.required_loopback_ports:
        item = by_port.get(port)
        name = f"free loopback port {port}"
        available = item is not None
        if item is not None:
            if item.listener_pid is not None:
                name += f" (pre-existing listener {item.listener_pid})"
            available = (
                item.host.casefold() in _LOOPBACK_HOSTS
                and item.listener_pid is None
                and item.bind_available
            )
        prerequisites.append(LocalPrerequisite(name, available))
    return tuple(prerequisites)


def admit_playwright_scenarios(
    inventory: PlaywrightScenarioInventory,
    observation: PlaywrightPreflightObservation,
) -> PlaywrightAdmissionResult:
    """Assign every disposition before launch without touching processes or ports."""
    prerequisites = _preflight_prerequisites(inventory, observation)
    network_policy = NetworkPolicy(
        NetworkMode.LOOPBACK_ONLY
        if observation.non_loopback_denial_enforceable
        else NetworkMode.NONE
    )
    scenarios = tuple(
        E2EScenario(
            scenario_id=item.scenario_id,
            requires_live_external_provider=item.requires_live_external_provider,
            included_by_configuration=item.included_by_configuration,
            prerequisites=prerequisites,
            network_policy=network_policy,
        )
        for item in inventory.scenarios
    )
    partition = partition_e2e_scenarios(scenarios)
    launch_admitted = bool(partition.execution_scenarios)
    may_invoke_cleanup = (
        launch_admitted
        and not inventory.harness_cleanup_kills_by_port
        and all(item.listener_pid is None for item in observation.loopback_ports)
    )
    return PlaywrightAdmissionResult(
        inventory=inventory,
        partition=partition,
        launch_admitted=launch_admitted,
        may_invoke_repository_harness_cleanup=may_invoke_cleanup,
    )
