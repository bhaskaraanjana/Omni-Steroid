"""Pure, fail-closed partitioning for discovered Local E2E scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .model_types import NetworkMode, NetworkPolicy


class E2EDisposition(StrEnum):
    """The four mutually exclusive Local E2E inventory dispositions."""

    EXTERNAL_PROVIDER_DEPENDENT = "external_provider_dependent"
    CONFIGURATION_EXCLUDED = "configuration_excluded"
    ENVIRONMENT_BLOCKED = "environment_blocked"
    EXECUTED = "executed"


@dataclass(frozen=True, slots=True)
class LocalPrerequisite:
    """A named local prerequisite evaluated before scenario execution."""

    name: str
    available: bool


@dataclass(frozen=True, slots=True)
class E2EScenario:
    """Provider, configuration, prerequisite, and policy metadata for one scenario."""

    scenario_id: str
    requires_live_external_provider: bool
    included_by_configuration: bool
    prerequisites: tuple[LocalPrerequisite, ...]
    network_policy: NetworkPolicy
    observed_failure: bool = False


@dataclass(frozen=True, slots=True)
class E2EScenarioDecision:
    """The single disposition and any named blockers for one scenario."""

    scenario: E2EScenario
    disposition: E2EDisposition
    unavailable_prerequisites: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class E2EPartition:
    """A complete scenario partition with execution and failure-count projections."""

    decisions: tuple[E2EScenarioDecision, ...]

    @property
    def execution_scenarios(self) -> tuple[E2EScenario, ...]:
        return tuple(
            item.scenario
            for item in self.decisions
            if item.disposition is E2EDisposition.EXECUTED
        )

    @property
    def local_product_failures(self) -> tuple[E2EScenario, ...]:
        return tuple(
            scenario for scenario in self.execution_scenarios if scenario.observed_failure
        )


def partition_e2e_scenarios(scenarios: tuple[E2EScenario, ...]) -> E2EPartition:
    """Assign exactly one safe disposition to every discovered scenario."""
    decisions: list[E2EScenarioDecision] = []
    for scenario in scenarios:
        unavailable: tuple[str, ...] = ()
        if scenario.requires_live_external_provider:
            disposition = E2EDisposition.EXTERNAL_PROVIDER_DEPENDENT
        elif not scenario.included_by_configuration:
            disposition = E2EDisposition.CONFIGURATION_EXCLUDED
        else:
            unavailable = tuple(
                prerequisite.name
                for prerequisite in scenario.prerequisites
                if not prerequisite.available
            )
            if scenario.network_policy.mode is not NetworkMode.LOOPBACK_ONLY:
                unavailable += ("loopback-only network containment",)
            disposition = (
                E2EDisposition.ENVIRONMENT_BLOCKED
                if unavailable
                else E2EDisposition.EXECUTED
            )
        decisions.append(E2EScenarioDecision(scenario, disposition, unavailable))
    return E2EPartition(tuple(decisions))
