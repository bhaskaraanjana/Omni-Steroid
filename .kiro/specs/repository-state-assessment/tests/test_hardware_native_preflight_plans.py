"""Unit tests for independent hardware/native plans and pure preflight records.

**Validates: Requirements 5.1–5.14**
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from assessor.baseline_models import OperatingSystemInventory
from assessor.evidence_models import AssessmentEnvironment
from assessor.execution_models import TerminationKind
from assessor.hardware_status import HardwareScope
from assessor.model_types import (
    AssessmentStatus,
    NetworkMode,
    VerificationPlane,
    ZonedTimestamp,
)
from assessor.native_check_plans import (
    NativeInputKind,
    build_native_check_plans,
)
from assessor.native_preflight import (
    NativePreflightObservation,
    preflight_native_check,
)


def _plans():
    return build_native_check_plans(
        cwd=r"C:\assessment mirror",
        run_root=r"C:\assessment run",
        tray_actions=("show_window", "quit"),
    )


def _environment() -> AssessmentEnvironment:
    return AssessmentEnvironment(
        operating_system=OperatingSystemInventory("Windows", "11", "26100"),
        hardware=(),
        tool_versions=(),
        safe_variable_names=("TEMP",),
    )


def _observations(plan, *, unavailable: str | None = None):
    return tuple(
        NativePreflightObservation(
            prerequisite_name=item.name,
            available=item.name != unavailable,
            detection_evidence=f"preflight/{plan.scope.value}/{index}.json",
            detection_detail=f"synthetic detection result for {item.name}",
        )
        for index, item in enumerate(plan.check_plan.prerequisites)
    )


def test_native_inventory_has_one_independent_plan_for_every_required_scope() -> None:
    plans = _plans()
    by_scope = {plan.scope: plan for plan in plans}

    assert set(by_scope) == set(HardwareScope)
    assert len(plans) == len({plan.check_plan.check_id for plan in plans})
    assert HardwareScope.DENSE_RETRIEVAL in by_scope
    assert HardwareScope.FALLBACK_RETRIEVAL in by_scope
    assert HardwareScope.GRAPHICS_PROCESSOR_SELECTION in by_scope
    assert HardwareScope.LOCAL_MODEL_INFERENCE in by_scope
    assert HardwareScope.TAURI_LAUNCH in by_scope
    assert HardwareScope.PYTHON_ENGINE_SIDECAR_LIFECYCLE in by_scope

    for plan in plans:
        check = plan.check_plan
        assert check.plane is VerificationPlane.HARDWARE_INTEGRATION
        assert check.numbered_procedure
        assert check.exact_argv is None
        assert check.timeout_ms == sum(item.deadline_ms for item in plan.observables)
        assert check.timeout_ms > 0
        assert check.network_policy.mode is NetworkMode.NONE
        assert not check.network_policy.permits_non_loopback
        assert check.write_policy.designated_roots == (r"C:\assessment run",)
        assert check.external_dependency is False
        assert check.cleanup_procedure
        assert any("conflict" in item.name for item in check.prerequisites)


def test_requirement_deadlines_and_exactly_once_operations_are_explicit() -> None:
    plans = {plan.scope: plan for plan in _plans()}

    assert [item.deadline_ms for item in plans[HardwareScope.MICROPHONE_CAPTURE].observables] == [
        10_000,
        10_000,
        5_000,
        5_000,
    ]
    assert [item.deadline_ms for item in plans[HardwareScope.SYSTEM_AUDIO_LOOPBACK_CAPTURE].observables] == [
        10_000,
        10_000,
        5_000,
        5_000,
    ]
    assert [item.deadline_ms for item in plans[HardwareScope.LOCAL_MODEL_INFERENCE].observables] == [
        300_000,
        300_000,
    ]
    assert plans[HardwareScope.LOCAL_MODEL_INFERENCE].exactly_once_operations == (
        "local model inference",
    )
    assert [item.deadline_ms for item in plans[HardwareScope.DENSE_RETRIEVAL].observables] == [
        120_000,
        120_000,
    ]
    assert [item.deadline_ms for item in plans[HardwareScope.TAURI_LAUNCH].observables] == [60_000]
    assert [item.deadline_ms for item in plans[HardwareScope.PYTHON_ENGINE_SIDECAR_LIFECYCLE].observables] == [
        30_000,
        10_000,
    ]
    assert [item.deadline_ms for item in plans[HardwareScope.TRAY_BEHAVIOR].observables] == [
        30_000,
        10_000,
        10_000,
    ]
    assert [item.deadline_ms for item in plans[HardwareScope.GLOBAL_HOTKEY_HANDLING].observables] == [5_000]
    assert [item.deadline_ms for item in plans[HardwareScope.SUPPORTED_TEXT_INJECTION].observables] == [5_000]


def test_safety_contract_allows_only_synthetic_non_private_inputs_and_no_audio_persistence() -> None:
    plans = {plan.scope: plan for plan in _plans()}

    assert plans[HardwareScope.MICROPHONE_CAPTURE].safety.input_kind is NativeInputKind.AUDIO
    assert plans[HardwareScope.SYSTEM_AUDIO_LOOPBACK_CAPTURE].safety.input_kind is NativeInputKind.AUDIO
    assert plans[HardwareScope.STT_ACCURACY].safety.input_kind is NativeInputKind.AUDIO
    assert plans[HardwareScope.SUPPORTED_TEXT_INJECTION].safety.input_kind is NativeInputKind.TEXT

    for plan in plans.values():
        assert plan.safety.synthetic_non_private_only
        assert not plan.safety.persist_audio
    assert plans[HardwareScope.SUPPORTED_TEXT_INJECTION].safety.disposable_target_required
    assert any(
        "disposable local target" in item.name
        for item in plans[HardwareScope.SUPPORTED_TEXT_INJECTION].check_plan.prerequisites
    )


def test_missing_preflight_prerequisite_creates_blocked_record_without_execution() -> None:
    plan = next(item for item in _plans() if item.scope is HardwareScope.MICROPHONE_CAPTURE)
    unavailable = plan.check_plan.prerequisites[1].name
    started_at = ZonedTimestamp(datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))

    result = preflight_native_check(
        plan=plan,
        observations=_observations(plan, unavailable=unavailable),
        started_at=started_at,
        environment=_environment(),
        source_revision="a" * 40,
    )

    assert not result.ready_for_scoped_behavior
    assert result.blocked_evidence is not None
    record = result.blocked_evidence.record
    assert record.check_id == plan.check_plan.check_id
    assert record.primary_status is AssessmentStatus.ENVIRONMENT_BLOCKED
    assert record.termination.kind is TerminationKind.PRECHECK_BLOCKED
    assert record.duration_ms == 0
    assert record.process_ownership.processes == ()
    assert record.rerun.numbered_procedure == plan.check_plan.numbered_procedure
    assert unavailable in record.rerun.prerequisites
    assert any(unavailable in line for line in record.relevant_output)


def test_complete_preflight_only_admits_plan_and_does_not_execute_behavior() -> None:
    plan = next(item for item in _plans() if item.scope is HardwareScope.SUPPORTED_TEXT_INJECTION)

    result = preflight_native_check(
        plan=plan,
        observations=_observations(plan),
        started_at=ZonedTimestamp(datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)),
        environment=_environment(),
        source_revision="b" * 40,
    )

    assert result.ready_for_scoped_behavior
    assert result.blocked_evidence is None
    assert all(item.available is True for item in result.resolved_plan.prerequisites)
    assert all(item.evidence_ref for item in result.resolved_plan.prerequisites)


def test_preflight_rejects_missing_extra_duplicate_or_behavior_executing_observations() -> None:
    plan = next(item for item in _plans() if item.scope is HardwareScope.GLOBAL_HOTKEY_HANDLING)
    observations = _observations(plan)
    common = {
        "plan": plan,
        "started_at": ZonedTimestamp(datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)),
        "environment": _environment(),
        "source_revision": "c" * 40,
    }

    with pytest.raises(ValueError, match="exactly"):
        preflight_native_check(observations=observations[:-1], **common)
    with pytest.raises(ValueError, match="exactly"):
        preflight_native_check(observations=observations + (observations[0],), **common)

    unsafe = NativePreflightObservation(
        prerequisite_name=observations[0].prerequisite_name,
        available=True,
        detection_evidence="preflight/unsafe.json",
        detection_detail="opened the device",
        scoped_behavior_executed=True,
    )
    with pytest.raises(ValueError, match="must not execute scoped behavior"):
        preflight_native_check(observations=(unsafe, *observations[1:]), **common)
