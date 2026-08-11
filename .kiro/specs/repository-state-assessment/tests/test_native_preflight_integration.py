"""Task 7.4 native fixture/preflight integration tests.

Validates Requirements 5.3, 5.4, 5.5, 5.7, 5.8, 5.9, 5.10, and 5.11.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from assessor.baseline_models import OperatingSystemInventory
from assessor.evidence_models import AssessmentEnvironment
from assessor.execution_models import Applicability
from assessor.hardware_status import (
    HardwareCheckOutcome,
    HardwareScope,
    classify_hardware_inventory,
    decide_hardware_status,
)
from assessor.model_types import AssessmentStatus, ZonedTimestamp
from assessor.native_check_plans import NativeCheckPlan, build_native_check_plans
from assessor.native_preflight import NativePreflightObservation, preflight_native_check

_CWD = r"C:\Assessment Ω\fixture vault"
_RUN_ROOT = r"C:\Assessment Ω\run artifacts"
_STARTED = ZonedTimestamp(datetime(2026, 7, 31, 3, 57, tzinfo=timezone.utc))


@dataclass
class _BoundedFake:
    succeed: bool = True
    calls: int = 0

    def invoke(self) -> bool:
        self.calls += 1
        return self.succeed


def _plans() -> dict[HardwareScope, NativeCheckPlan]:
    return {
        plan.scope: plan
        for plan in build_native_check_plans(
            cwd=_CWD, run_root=_RUN_ROOT, tray_actions=("show window",)
        )
    }


def _environment() -> AssessmentEnvironment:
    return AssessmentEnvironment(
        operating_system=OperatingSystemInventory("Fixture OS", "1", "synthetic"),
        hardware=(),
        tool_versions=(),
        safe_variable_names=(),
    )


def _observations(
    plan: NativeCheckPlan, unavailable: tuple[str, ...] = ()
) -> tuple[NativePreflightObservation, ...]:
    return tuple(
        NativePreflightObservation(
            prerequisite_name=item.name,
            available=item.name not in unavailable,
            detection_evidence=f"evidence/preflight/{plan.scope.value}/{index}.json",
            detection_detail=(
                "conflicting prose says healthy; authoritative boolean is unavailable"
                if item.name in unavailable
                else "available from bounded synthetic fixture"
            ),
        )
        for index, item in enumerate(plan.check_plan.prerequisites)
    )


def _run_fixture(
    plan: NativeCheckPlan,
    observations: tuple[NativePreflightObservation, ...],
    procedure: _BoundedFake,
) -> HardwareCheckOutcome:
    admission = preflight_native_check(
        plan=plan,
        observations=observations,
        started_at=_STARTED,
        environment=_environment(),
        source_revision="f" * 40,
    )
    if not admission.ready_for_scoped_behavior:
        assert admission.blocked_evidence is not None
        return HardwareCheckOutcome(
            plan.scope,
            Applicability.APPLICABLE,
            False,
            False,
            False,
            False,
            False,
            admission.blocked_evidence.record.evidence_id,
        )
    succeeded = procedure.invoke()
    return HardwareCheckOutcome(
        plan.scope,
        Applicability.APPLICABLE,
        True,
        True,
        succeeded,
        False,
        not succeeded,
        f"evidence/execution/{plan.scope.value}.json",
    )


def test_blocked_preflight_never_invokes_scoped_behavior() -> None:
    """A partially available device and contradictory prose must fail closed before use."""
    plan = _plans()[HardwareScope.MICROPHONE_CAPTURE]
    missing = ("microphone permission",)
    fake = _BoundedFake()

    outcome = _run_fixture(plan, _observations(plan, missing), fake)
    decision = decide_hardware_status(outcome)

    assert fake.calls == 0
    assert decision.primary_status is AssessmentStatus.ENVIRONMENT_BLOCKED
    assert outcome.execution_attempted is False
    # The blocked decision must cite the preflight's own evidence record, scoped to this device
    # exactly -- a prefix match would let another scope's reference satisfy the assertion.
    assert decision.evidence_ref == "evidence-hardware-microphone_capture"
    assert plan.check_plan.cwd == _CWD
    assert plan.check_plan.write_policy.designated_roots == (_RUN_ROOT,)

    observations = _observations(plan)
    conflict = NativePreflightObservation(
        observations[0].prerequisite_name,
        False,
        "evidence/conflicting-device.json",
        "same device reported unavailable",
    )
    with pytest.raises(ValueError, match="exactly once"):
        preflight_native_check(
            plan=plan,
            observations=(*observations, conflict),
            started_at=_STARTED,
            environment=_environment(),
            source_revision="f" * 40,
        )


def test_absence_and_post_availability_malfunction_never_collapse() -> None:
    """Preflight absence is blocked while a bounded fake failure is integration failure."""
    plan = _plans()[HardwareScope.SYSTEM_AUDIO_LOOPBACK_CAPTURE]
    blocked_fake, broken_fake = _BoundedFake(), _BoundedFake(succeed=False)
    blocked = decide_hardware_status(
        _run_fixture(plan, _observations(plan, ("system-audio loopback driver",)), blocked_fake)
    )
    failed = decide_hardware_status(_run_fixture(plan, _observations(plan), broken_fake))

    assert (blocked.primary_status, failed.primary_status) == (
        AssessmentStatus.ENVIRONMENT_BLOCKED,
        AssessmentStatus.INTEGRATION_FAILED,
    )
    assert blocked.primary_status is not failed.primary_status
    assert (blocked_fake.calls, broken_fake.calls) == (0, 1)
    assert blocked.evidence_ref != failed.evidence_ref


def test_dense_block_and_fallback_success_are_separate_results() -> None:
    """Unavailable dense weights cannot borrow the independently measured fallback success."""
    plans = _plans()
    dense, fallback = _BoundedFake(), _BoundedFake()
    dense_result = decide_hardware_status(
        _run_fixture(
            plans[HardwareScope.DENSE_RETRIEVAL],
            _observations(
                plans[HardwareScope.DENSE_RETRIEVAL], ("Dense_Retrieval_Weights",)
            ),
            dense,
        )
    )
    fallback_result = decide_hardware_status(
        _run_fixture(
            plans[HardwareScope.FALLBACK_RETRIEVAL],
            _observations(plans[HardwareScope.FALLBACK_RETRIEVAL]),
            fallback,
        )
    )

    assert dense_result.scope is HardwareScope.DENSE_RETRIEVAL
    assert dense_result.primary_status is AssessmentStatus.ENVIRONMENT_BLOCKED
    assert fallback_result.scope is HardwareScope.FALLBACK_RETRIEVAL
    assert fallback_result.primary_status is AssessmentStatus.VERIFIED_WORKING
    assert dense_result.evidence_ref != fallback_result.evidence_ref
    assert (dense.calls, fallback.calls) == (0, 1)


def test_native_inventory_rejects_empty_or_duplicate_status_evidence() -> None:
    """Every native scope has exactly one status/evidence row; empty or duplicate sets fail."""
    outcomes = tuple(
        HardwareCheckOutcome(
            scope,
            Applicability.APPLICABLE,
            True,
            True,
            True,
            False,
            False,
            f"evidence/native/{scope.value}.json",
        )
        for scope in HardwareScope
    )
    inventory = classify_hardware_inventory(outcomes)

    assert len(inventory.decisions) == len(HardwareScope)
    assert len({row.scope for row in inventory.decisions}) == len(HardwareScope)
    assert len({row.evidence_ref for row in inventory.decisions}) == len(HardwareScope)
    assert all(isinstance(row.primary_status, AssessmentStatus) for row in inventory.decisions)
    with pytest.raises(ValueError, match="every required scope exactly once"):
        classify_hardware_inventory(())
    with pytest.raises(ValueError, match="unique scopes"):
        classify_hardware_inventory((*outcomes, outcomes[0]))
