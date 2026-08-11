"""Property 10: Hardware status distinguishes absence from malfunction.

**Validates: Requirements 5.5, 5.7, 5.9, 5.10, 5.11, 8.5, 8.6, 8.12**
"""

from __future__ import annotations

import random

from assessor.execution_models import Applicability
from assessor.hardware_status import (
    HardwareCheckOutcome,
    HardwareScope,
    classify_hardware_inventory,
)
from assessor.model_types import AssessmentStatus

_SEED = 20260710
_CASES = 256


def _expected_status(outcome: HardwareCheckOutcome) -> AssessmentStatus:
    if outcome.applicability is Applicability.NOT_APPLICABLE:
        return AssessmentStatus.NOT_APPLICABLE
    if not outcome.prerequisites_available:
        return AssessmentStatus.ENVIRONMENT_BLOCKED
    if not outcome.execution_attempted:
        return AssessmentStatus.UNVERIFIED
    if outcome.malfunction_observed:
        return AssessmentStatus.INTEGRATION_FAILED
    if outcome.required_outcomes_complete:
        return AssessmentStatus.VERIFIED_WORKING
    if outcome.subset_verified:
        return AssessmentStatus.VERIFIED_PARTIAL
    return AssessmentStatus.INTEGRATION_FAILED


def _outcome(rng: random.Random, case: int, scope: HardwareScope) -> HardwareCheckOutcome:
    return HardwareCheckOutcome(
        scope=scope,
        applicability=rng.choice(tuple(Applicability)),
        prerequisites_available=rng.choice((True, False)),
        execution_attempted=rng.choice((True, False)),
        required_outcomes_complete=rng.choice((True, False)),
        subset_verified=rng.choice((True, False)),
        malfunction_observed=rng.choice((True, False)),
        evidence_ref=f"evidence-{case}-{scope.value}",
    )


def test_preflight_absence_and_confirmed_malfunction_are_distinct() -> None:
    outcomes = tuple(
        HardwareCheckOutcome(
            scope=scope,
            applicability=Applicability.APPLICABLE,
            prerequisites_available=scope is not HardwareScope.DENSE_RETRIEVAL,
            execution_attempted=scope is not HardwareScope.DENSE_RETRIEVAL,
            required_outcomes_complete=False,
            subset_verified=False,
            malfunction_observed=scope is HardwareScope.LOCAL_MODEL_INFERENCE,
            evidence_ref=f"evidence-{scope.value}",
        )
        for scope in HardwareScope
    )

    inventory = classify_hardware_inventory(outcomes)
    decisions = {decision.scope: decision for decision in inventory.decisions}

    assert decisions[HardwareScope.DENSE_RETRIEVAL].primary_status is (
        AssessmentStatus.ENVIRONMENT_BLOCKED
    )
    assert HardwareScope.DENSE_RETRIEVAL not in inventory.product_failure_scopes
    assert decisions[HardwareScope.LOCAL_MODEL_INFERENCE].primary_status is (
        AssessmentStatus.INTEGRATION_FAILED
    )
    assert HardwareScope.LOCAL_MODEL_INFERENCE in inventory.product_failure_scopes


def test_property_10_hardware_status_distinguishes_absence_from_malfunction() -> None:
    """Generate 256 applicability/preflight/execution/subset/malfunction inventories."""
    rng = random.Random(_SEED)
    seen: dict[str, set[object]] = {
        "applicability": set(),
        "prerequisite": set(),
        "execution": set(),
        "subset": set(),
        "malfunction": set(),
    }

    for case in range(_CASES):
        outcomes = tuple(_outcome(rng, case, scope) for scope in HardwareScope)
        inventory = classify_hardware_inventory(outcomes)

        assert len(inventory.decisions) == len(HardwareScope)
        assert {decision.scope for decision in inventory.decisions} == set(HardwareScope)
        assert len({decision.scope for decision in inventory.decisions}) == len(
            inventory.decisions
        )

        for outcome, decision in zip(outcomes, inventory.decisions, strict=True):
            seen["applicability"].add(outcome.applicability)
            seen["prerequisite"].add(outcome.prerequisites_available)
            seen["execution"].add(outcome.execution_attempted)
            seen["subset"].add(outcome.subset_verified)
            seen["malfunction"].add(outcome.malfunction_observed)

            assert decision.scope is outcome.scope
            assert decision.primary_status is _expected_status(outcome)
            assert isinstance(decision.primary_status, AssessmentStatus)
            assert decision.evidence_ref == outcome.evidence_ref

            if (
                outcome.applicability is Applicability.APPLICABLE
                and not outcome.prerequisites_available
            ):
                assert decision.primary_status is AssessmentStatus.ENVIRONMENT_BLOCKED
                assert decision.scope not in inventory.product_failure_scopes
            if (
                outcome.applicability is Applicability.APPLICABLE
                and outcome.prerequisites_available
                and outcome.execution_attempted
                and outcome.malfunction_observed
            ):
                assert decision.primary_status is AssessmentStatus.INTEGRATION_FAILED
                assert decision.scope in inventory.product_failure_scopes

        assert inventory.product_failure_scopes == tuple(
            decision.scope
            for decision in inventory.decisions
            if decision.primary_status is AssessmentStatus.INTEGRATION_FAILED
        )

    assert _CASES >= 100
    assert seen["applicability"] == set(Applicability)
    assert all(seen[dimension] == {True, False} for dimension in seen if dimension != "applicability")
