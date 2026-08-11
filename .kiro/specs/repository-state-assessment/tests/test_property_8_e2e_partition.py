"""Property 8: E2E scenarios form an exhaustive, safe partition.

**Validates: Requirements 4.1, 4.5, 4.9, 4.10, 7.1, 7.2**
"""

from __future__ import annotations

import random

from assessor import (
    E2EDisposition,
    E2EScenario,
    LocalPrerequisite,
    NetworkMode,
    NetworkPolicy,
    partition_e2e_scenarios,
)

_SEED = 20260708
_CASES = 256


def _scenario(rng: random.Random, number: int) -> E2EScenario:
    """Generate all core boolean combinations plus varied prerequisite inventories."""
    mask = number % 64
    prerequisites = [
        LocalPrerequisite("production frontend", bool(mask & 4)),
        LocalPrerequisite("local Python engine", bool(mask & 8)),
    ]
    prerequisites.extend(
        LocalPrerequisite(f"local fixture {index}", rng.choice((True, False)))
        for index in range(rng.randint(0, 3))
    )
    return E2EScenario(
        scenario_id=f"scenario-{number}",
        requires_live_external_provider=bool(mask & 1),
        included_by_configuration=bool(mask & 2),
        prerequisites=tuple(prerequisites),
        network_policy=NetworkPolicy(
            NetworkMode.LOOPBACK_ONLY if mask & 16 else NetworkMode.NONE
        ),
        observed_failure=bool(mask & 32),
    )


def _expected_disposition(scenario: E2EScenario) -> E2EDisposition:
    if scenario.requires_live_external_provider:
        return E2EDisposition.EXTERNAL_PROVIDER_DEPENDENT
    if not scenario.included_by_configuration:
        return E2EDisposition.CONFIGURATION_EXCLUDED
    if any(not item.available for item in scenario.prerequisites):
        return E2EDisposition.ENVIRONMENT_BLOCKED
    if scenario.network_policy.mode is not NetworkMode.LOOPBACK_ONLY:
        return E2EDisposition.ENVIRONMENT_BLOCKED
    return E2EDisposition.EXECUTED


def test_provider_dependent_failure_is_omitted_and_not_counted() -> None:
    scenario = E2EScenario(
        scenario_id="ask-live-provider",
        requires_live_external_provider=True,
        included_by_configuration=True,
        prerequisites=(LocalPrerequisite("browser", True),),
        network_policy=NetworkPolicy(NetworkMode.LOOPBACK_ONLY),
        observed_failure=True,
    )

    partition = partition_e2e_scenarios((scenario,))

    assert partition.decisions[0].disposition is E2EDisposition.EXTERNAL_PROVIDER_DEPENDENT
    assert partition.execution_scenarios == ()
    assert partition.local_product_failures == ()


def test_property_8_e2e_scenarios_form_an_exhaustive_safe_partition() -> None:
    """Generate 256 provider/config/prerequisite/policy combinations."""
    rng = random.Random(_SEED)
    generated = tuple(_scenario(rng, number) for number in range(_CASES))

    # Vary inventory boundaries as well as scenario metadata.
    for start in range(0, _CASES, 7):
        scenarios = generated[start : start + 7]
        partition = partition_e2e_scenarios(scenarios)

        assert len(partition.decisions) == len(scenarios)
        assert tuple(item.scenario for item in partition.decisions) == scenarios
        assert all(
            isinstance(item.disposition, E2EDisposition)
            for item in partition.decisions
        )
        assert tuple(item.disposition for item in partition.decisions) == tuple(
            _expected_disposition(scenario) for scenario in scenarios
        )

        expected_execution = tuple(
            item.scenario
            for item in partition.decisions
            if item.disposition is E2EDisposition.EXECUTED
        )
        assert partition.execution_scenarios == expected_execution
        assert all(
            scenario.included_by_configuration
            and not scenario.requires_live_external_provider
            and all(item.available for item in scenario.prerequisites)
            and scenario.network_policy.mode is NetworkMode.LOOPBACK_ONLY
            and not scenario.network_policy.permits_non_loopback
            for scenario in partition.execution_scenarios
        )

        provider_dependent = {
            item.scenario
            for item in partition.decisions
            if item.disposition is E2EDisposition.EXTERNAL_PROVIDER_DEPENDENT
        }
        assert provider_dependent.isdisjoint(partition.execution_scenarios)
        assert provider_dependent.isdisjoint(partition.local_product_failures)
        assert partition.local_product_failures == tuple(
            scenario
            for scenario in partition.execution_scenarios
            if scenario.observed_failure
        )

    assert len(generated) >= 100
    assert {number % 64 for number in range(_CASES)} == set(range(64))
