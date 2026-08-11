"""Task 8.3 examples for security inventory and hermetic probe admission.

**Validates: Requirements 7.1-7.11**
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

import pytest

from assessor import AssessmentStatus, RawSecurityArtifact, SecurityControl, SensitiveCategory, SensitiveMarker
from assessor.baseline_models import OperatingSystemInventory
from assessor.evidence_models import AssessmentEnvironment
from assessor.external_action_refusal import ExternalActionRequest, RefusalCondition, UserDataHash, refuse_external_action
from assessor.model_types import ProcessOwnership, ZonedTimestamp
from assessor.security_control_assessment import (
    SECURITY_CONTROL_INVENTORY,
    SecurityAssessmentContext,
    SecurityProbeMode,
    SecurityProbeResult,
    assess_security_controls,
    build_credential_free_probe_environment,
)


def _context() -> SecurityAssessmentContext:
    return SecurityAssessmentContext(
        started_at=ZonedTimestamp(datetime(2026, 7, 11, tzinfo=timezone.utc)),
        environment=AssessmentEnvironment(OperatingSystemInventory("Windows", "11", "26100"), (), (), ("PYTHONUTF8",)),
        source_revision="abc123",
        cwd=r"C:\assessment mirror",
    )


def _static(control: SecurityControl) -> SecurityProbeResult:
    secret = f"synthetic-secret-{control.value}"
    return SecurityProbeResult(
        control=control,
        mode=SecurityProbeMode.STATIC_INSPECTION,
        complete_scope=True,
        relevant_output=(f"found {secret}",),
        artifacts=(RawSecurityArtifact(f"artifact-{control.value}", f"evidence {secret}", True),),
        sensitive_markers=(SensitiveMarker(SensitiveCategory.SECRET, secret),),
    )

def _dynamic(control: SecurityControl, condition: RefusalCondition) -> SecurityProbeResult:
    hashes = (UserDataHash("[USER_DATA]", sha256(b"unchanged").hexdigest()),)
    refusal = refuse_external_action(ExternalActionRequest(f"action-{control.value}", control.value, "synthetic"), condition, hashes)
    return SecurityProbeResult(
        control=control,
        mode=SecurityProbeMode.HERMETIC_EXECUTION,
        complete_scope=True,
        relevant_output=("observable refusal",),
        refusal=refusal,
        synthetic_non_private_input=True,
        disposable_state=True,
        inherited_credentials=False,
        network_loopback_only=True,
        process_ownership=ProcessOwnership(f"owned-{control.value}", "disposable process", (), True),
        network_observation_ref=f"network-{control.value}",
        write_audit_ref=f"writes-{control.value}",
    )


def test_inventory_is_complete_and_each_control_gets_separate_evidence() -> None:
    assert tuple(item.control for item in SECURITY_CONTROL_INVENTORY) == tuple(SecurityControl)
    dynamic = {
        SecurityControl.KILL_SWITCH: RefusalCondition.ABSENT_CREDENTIALS,
        SecurityControl.APPROVAL_BEFORE_EXECUTE: RefusalCondition.REJECTING_LOOPBACK_FAKE,
        SecurityControl.GMAIL_DRAFT_ONLY: RefusalCondition.REJECTING_LOOPBACK_FAKE,
    }
    probes = tuple(_dynamic(control, dynamic[control]) if control in dynamic else _static(control) for control in SecurityControl)

    assessment = assess_security_controls(probes, _context())

    assert len(assessment.controls) == len(SecurityControl)
    assert tuple(item.record.control for item in assessment.controls) == tuple(SecurityControl)
    assert all(item.evidence.primary_status is AssessmentStatus.VERIFIED_WORKING for item in assessment.controls)
    assert all(len(item.record.methods.values()) == 5 for item in assessment.controls)
    assert assessment.by_control(SecurityControl.APPROVAL_BEFORE_EXECUTE).record.methods.mocked
    assert not assessment.by_control(SecurityControl.KILL_SWITCH).record.methods.mocked
    permanent = "\n".join(assessment.by_control(SecurityControl.LOCAL_ONLY_STORAGE).record.relevant_output)
    assert "synthetic-secret-local_only_storage" not in permanent
    assert SensitiveCategory.SECRET.label in permanent


def test_probe_environment_never_inherits_or_accepts_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-parent-secret")
    environment = build_credential_free_probe_environment(tmp_path, (("PYTHONUTF8", "1"),))
    assert environment.inherits_parent is False
    assert "synthetic-parent-secret" not in dict(environment.values).values()
    assert "GEMINI_API_KEY" not in dict(environment.values)
    with pytest.raises(ValueError, match="credential-like"):
        build_credential_free_probe_environment(tmp_path, (("OAUTH_TOKEN", "synthetic"),))


def test_provider_payloads_and_non_loopback_observations_are_rejected() -> None:
    with pytest.raises(ValueError, match="provider payload"):
        SecurityProbeResult(
            control=SecurityControl.GMAIL_DRAFT_ONLY,
            mode=SecurityProbeMode.HERMETIC_EXECUTION,
            complete_scope=False,
            provider_payload_count=1,
            synthetic_non_private_input=True,
            disposable_state=True,
            inherited_credentials=False,
            network_loopback_only=True,
        )


def test_unexecuted_control_is_unverified_without_a_named_blocker() -> None:
    probes = tuple(
        SecurityProbeResult(
            control=control,
            mode=SecurityProbeMode.HERMETIC_EXECUTION,
            complete_scope=False,
            unavailable_prerequisites=("local DPAPI facility",) if control is SecurityControl.KEY_CUSTODY else (),
        )
        if control in {SecurityControl.KEY_CUSTODY, SecurityControl.KILL_SWITCH}
        else _static(control)
        for control in SecurityControl
    )
    assessment = assess_security_controls(probes, _context())
    assert assessment.by_control(SecurityControl.KEY_CUSTODY).evidence.primary_status is AssessmentStatus.ENVIRONMENT_BLOCKED
    assert assessment.by_control(SecurityControl.KILL_SWITCH).evidence.primary_status is AssessmentStatus.UNVERIFIED
