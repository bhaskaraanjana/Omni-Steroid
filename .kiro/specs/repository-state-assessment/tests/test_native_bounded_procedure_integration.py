"""Task 7.4 native bounded-procedure integration tests.

Validates Requirements 5.3, 5.4, 5.5, 5.7, 5.8, 5.9, 5.10, and 5.11.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256

import pytest

from assessor.baseline_models import OperatingSystemInventory
from assessor.evidence_models import AssessmentEnvironment
from assessor.execution_models import Applicability
from assessor.hardware_status import HardwareCheckOutcome, HardwareScope, decide_hardware_status
from assessor.model_types import (
    AssessmentStatus,
    OwnedProcess,
    ProcessOwnership,
    ZonedTimestamp,
)
from assessor.native_check_plans import NativeCheckPlan, build_native_check_plans
from assessor.native_preflight import NativePreflightObservation, preflight_native_check
from assessor.preservation import AffectedContent, OmissionEvidence, OmittedDependentCheck
from assessor.process_cleanup import CleanupMode, ProcessSnapshot, select_cleanup_processes
from assessor.stt_accuracy import STTAccuracyContext, synthesize_stt_accuracy

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


def _observations(plan: NativeCheckPlan) -> tuple[NativePreflightObservation, ...]:
    return tuple(
        NativePreflightObservation(
            prerequisite_name=item.name,
            available=True,
            detection_evidence=f"evidence/preflight/{plan.scope.value}/{index}.json",
            detection_detail="available from bounded synthetic fixture",
        )
        for index, item in enumerate(plan.check_plan.prerequisites)
    )


def _run_fixture(plan: NativeCheckPlan, procedure: _BoundedFake) -> HardwareCheckOutcome:
    admission = preflight_native_check(
        plan=plan,
        observations=_observations(plan),
        started_at=_STARTED,
        environment=_environment(),
        source_revision="f" * 40,
    )
    assert admission.ready_for_scoped_behavior
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


def _unsafe_injection_omission(plan: NativeCheckPlan, target: str) -> OmissionEvidence:
    payload = "synthetic Ω text".encode()
    return OmissionEvidence(
        operation_id=plan.check_plan.check_id,
        command_or_procedure=plan.check_plan.numbered_procedure or (),
        affected_content=(AffectedContent(target, len(payload), sha256(payload).hexdigest()),),
        reason="target is not disposable and assessment-owned; text injection omitted",
        dependent_checks=(OmittedDependentCheck(plan.check_plan.check_id),),
    )


def test_missing_stt_inputs_omit_wer_but_measured_zero_survives() -> None:
    """Missing corpus/model has no number, whereas a measured Decimal zero remains present."""
    for blockers in (
        ("labelled local synthetic speech corpus",),
        ("speech Local_Model",),
    ):
        blocked = synthesize_stt_accuracy(
            word_error_rate_percent=None,
            context=None,
            blockers=blockers,
            primary_status=AssessmentStatus.ENVIRONMENT_BLOCKED,
            evidence_reference=f"evidence/{blockers[0]}.json",
        )
        assert blocked.word_error_rate_percent is None
        assert blocked.blockers == blockers

    zero = synthesize_stt_accuracy(
        word_error_rate_percent=Decimal("0.0"),
        context=STTAccuracyContext(2, Decimal("1.25"), "en-Ω", "fixture model", "fake GPU"),
        blockers=(),
        primary_status=AssessmentStatus.VERIFIED_WORKING,
        evidence_reference="evidence/measured zero.json",
    )
    assert zero.word_error_rate_percent == Decimal("0.0")
    assert zero.word_error_rate_percent is not None
    assert zero.blockers == ()


def test_gpu_fixture_executes_exactly_one_inference() -> None:
    """An admitted GPU/model fixture calls inference once, not zero times or twice."""
    plan = _plans()[HardwareScope.LOCAL_MODEL_INFERENCE]
    inference = _BoundedFake()
    decision = decide_hardware_status(_run_fixture(plan, inference))

    assert plan.exactly_once_operations == ("local model inference",)
    assert inference.calls == 1
    assert decision.primary_status is AssessmentStatus.VERIFIED_WORKING
    assert max(item.deadline_ms for item in plan.observables) == 300_000


@pytest.mark.parametrize("mode", tuple(CleanupMode))
def test_sidecar_cleanup_preserves_preexisting_process_on_every_exit(mode: CleanupMode) -> None:
    """Success, failure, timeout, and abort select only the assessment-owned sidecar."""
    created = ZonedTimestamp(datetime(2026, 7, 31, 3, 58, tzinfo=timezone.utc))
    sidecar = OwnedProcess(4101, created, r"C:\Assessment Ω\fake sidecar.exe", 4100)
    preexisting = OwnedProcess(99, created, r"C:\Program Files\Existing\sidecar.exe")
    ownership = ProcessOwnership("assessment-token", "bounded-fake", (sidecar,))
    owned_snapshot = ProcessSnapshot(sidecar, "assessment-token")
    preexisting_snapshot = ProcessSnapshot(preexisting, None)

    selection = select_cleanup_processes(
        ownership, (preexisting_snapshot, owned_snapshot), mode
    )

    assert selection.mode is mode
    assert selection.terminate == (owned_snapshot,)
    assert selection.preserve == (preexisting_snapshot,)
    sidecar_plan = _plans()[HardwareScope.PYTHON_ENGINE_SIDECAR_LIFECYCLE]
    assert sidecar_plan.check_plan.timeout_ms == 40_000
    assert "only assessment-owned" in sidecar_plan.check_plan.cleanup_procedure[0]


def test_unsafe_text_injection_is_omitted_with_complete_record() -> None:
    """A non-owned target yields complete omission evidence and never calls injection."""
    plan = _plans()[HardwareScope.SUPPORTED_TEXT_INJECTION]
    injection = _BoundedFake()
    target = r"C:\Users\fixture\Existing Notes Ω.txt"
    omission = _unsafe_injection_omission(plan, target)

    assert plan.safety.disposable_target_required is True
    assert injection.calls == 0
    assert omission.operation_id == "hardware-supported_text_injection"
    assert omission.command_or_procedure == plan.check_plan.numbered_procedure
    assert omission.affected_content[0].path == target
    assert omission.affected_content[0].size_bytes > 0
    assert len(omission.affected_content[0].sha256) == 64
    assert "not disposable and assessment-owned" in omission.reason
    assert omission.dependent_checks[0].status is AssessmentStatus.UNVERIFIED
