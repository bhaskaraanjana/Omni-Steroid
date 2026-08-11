"""Task 8.4 security integration tests for Requirements 7.1, 7.2, and 7.6-7.11."""

from __future__ import annotations

import json
import socket
import threading
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from assessor.baseline_models import OperatingSystemInventory
from assessor.contained_process_environment import build_contained_environment
from assessor.evidence_models import AssessmentEnvironment
from assessor.execution_models import Applicability
from assessor.external_action_refusal import (
    ExternalActionRequest,
    PendingActionState,
    RefusalCondition,
    UserDataHash,
    refuse_external_action,
)
from assessor.model_types import AssessmentStatus, ProcessOwnership, ZonedTimestamp
from assessor.security_control_assessment import (
    SecurityAssessmentContext,
    SecurityProbeMode,
    SecurityProbeResult,
    assess_security_controls,
)
from assessor.security_records import (
    RawSecurityArtifact,
    SecurityControl,
    SensitiveCategory,
    SensitiveMarker,
)
from assessor.status_decision import StatusDecisionFacts, decide_status

_SECRET = "sk_test_only_NOT_REAL_7f9d"
_COUNT_RECORD = (
    "live_provider_call_count=0; provider_payload_count=0; "
    "provider_side_effect_count=0; non_loopback_request_count=0"
)


def _context(run_root: Path) -> SecurityAssessmentContext:
    return SecurityAssessmentContext(
        started_at=ZonedTimestamp(datetime(2026, 7, 31, tzinfo=timezone.utc)),
        environment=AssessmentEnvironment(
            OperatingSystemInventory("Windows", "11", "synthetic"), (), (), ("PYTHONUTF8",)
        ),
        source_revision="synthetic-revision-8.4",
        cwd=str(run_root),
    )


def _reject_mid_handshake() -> tuple[bytes, bytes]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.settimeout(2)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    endpoint = listener.getsockname()
    received: list[bytes] = []
    peer_addresses: list[str] = []
    errors: list[BaseException] = []

    def reject() -> None:
        try:
            connection, peer = listener.accept()
            with connection:
                connection.settimeout(2)
                peer_addresses.append(peer[0])
                received.append(connection.recv(4096))
                connection.sendall(b"REJECT before action payload\n")
        except BaseException as error:  # pragma: no cover - surfaced in caller
            errors.append(error)
        finally:
            listener.close()

    thread = threading.Thread(target=reject, name="rejecting-loopback-fake")
    thread.start()
    with socket.create_connection(endpoint, timeout=2) as client:
        client.sendall(b"CLIENT_HELLO synthetic\n")
        rejection = client.recv(4096)
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert errors == []
    assert peer_addresses == ["127.0.0.1"]
    assert received == [b"CLIENT_HELLO synthetic\n"]
    assert rejection == b"REJECT before action payload\n"
    return received[0], rejection


def _static_probe(
    control: SecurityControl,
    artifacts: tuple[RawSecurityArtifact, ...] = (),
    markers: tuple[SensitiveMarker, ...] = (),
    output: tuple[str, ...] = (_COUNT_RECORD,),
) -> SecurityProbeResult:
    return SecurityProbeResult(
        control=control,
        mode=SecurityProbeMode.STATIC_INSPECTION,
        complete_scope=True,
        relevant_output=output,
        artifacts=artifacts,
        sensitive_markers=markers,
    )


def _dynamic_probe(
    control: SecurityControl,
    condition: RefusalCondition,
    hashes: tuple[UserDataHash, ...],
) -> SecurityProbeResult:
    if condition is RefusalCondition.REJECTING_LOOPBACK_FAKE:
        hello, rejection = _reject_mid_handshake()
        assert b"action payload" not in hello
        assert rejection.startswith(b"REJECT")
    refusal = refuse_external_action(
        ExternalActionRequest(f"action-{control.value}", control.value, "synthetic payload"),
        condition,
        hashes,
    )
    return SecurityProbeResult(
        control=control,
        mode=SecurityProbeMode.HERMETIC_EXECUTION,
        complete_scope=True,
        relevant_output=(_COUNT_RECORD, refusal.failure_indication),
        refusal=refusal,
        synthetic_non_private_input=True,
        disposable_state=True,
        network_loopback_only=True,
        process_ownership=ProcessOwnership(f"owned-{control.value}", "test thread", (), True),
        network_observation_ref=f"loopback-only-{control.value}",
        write_audit_ref=f"unchanged-hashes-{control.value}",
    )


def _all_static_probes() -> tuple[SecurityProbeResult, ...]:
    return tuple(_static_probe(control) for control in SecurityControl)


def test_hermetic_refusal_run_preserves_bytes_and_publishes_only_sanitized_records(
    tmp_path: Path,
) -> None:
    """Pin the complete synthetic refusal, quarantine, redaction, and evidence path."""
    run_root = tmp_path / "rûn root 東京 with spaces"
    run_root.mkdir()
    environment = build_contained_environment(
        run_root,
        "security-integration",
        {"PATH": "C:\\synthetic tools", "GEMINI_API_KEY": _SECRET},
    )
    assert _SECRET not in json.dumps(environment, ensure_ascii=False)
    assert environment["OMNI_ENV_FILE"].startswith(str(run_root))

    user_path = run_root / "process-data" / "security-integration" / "data" / "vault" / "Résumé 東京.md"
    original_bytes = "synthetic user text\r\nsecond line\n".encode()
    user_path.write_bytes(original_bytes)
    before_digest = sha256(original_bytes).hexdigest()
    hashes = (UserDataHash("[USER_DATA_PATH]", before_digest),)

    raw_path = run_root / f"raw stack {_SECRET} 東京.log"
    nested = {"outer": [{"credential": _SECRET}], "private": "synthetic private excerpt"}
    raw_bytes = (
        json.dumps(nested, ensure_ascii=False)
        + f"\nTraceback: File '{raw_path}', line 9, token={_SECRET}\n"
    ).encode()
    raw_path.write_bytes(raw_bytes)
    markers = (
        SensitiveMarker(SensitiveCategory.SECRET, _SECRET),
        SensitiveMarker(SensitiveCategory.PRIVATE_PATH, str(raw_path)),
        SensitiveMarker(SensitiveCategory.PRIVATE_CONTENT, "synthetic private excerpt"),
    )
    artifacts = (
        RawSecurityArtifact("quarantined-raw-stack", raw_bytes.decode(), False),
        RawSecurityArtifact(f"published-{_SECRET}-stack", raw_bytes.decode(), True),
    )
    probes = []
    for control in SecurityControl:
        if control is SecurityControl.KILL_SWITCH:
            probes.append(_dynamic_probe(control, RefusalCondition.ABSENT_CREDENTIALS, hashes))
        elif control in {SecurityControl.APPROVAL_BEFORE_EXECUTE, SecurityControl.GMAIL_DRAFT_ONLY}:
            probes.append(_dynamic_probe(control, RefusalCondition.REJECTING_LOOPBACK_FAKE, hashes))
        elif control is SecurityControl.LOCAL_ONLY_STORAGE:
            probes.append(_static_probe(control, artifacts, markers, (_COUNT_RECORD, raw_bytes.decode())))
        else:
            probes.append(_static_probe(control))

    assessment = assess_security_controls(tuple(probes), _context(run_root))

    assert user_path.read_bytes() == original_bytes
    assert sha256(user_path.read_bytes()).hexdigest() == before_digest
    assert raw_path.read_bytes() == raw_bytes
    assert assessment.withheld_artifact_ids == ("quarantined-raw-stack",)
    assert tuple(item.record.control for item in assessment.controls) == tuple(SecurityControl)
    assert len(assessment.controls) == len(set(SecurityControl)) == 8
    assert all(item.evidence.primary_status is AssessmentStatus.VERIFIED_WORKING for item in assessment.controls)
    assert all(_COUNT_RECORD in item.record.relevant_output for item in assessment.controls)
    assert sum(probe.live_provider_call_count for probe in probes) == 0
    assert sum(probe.provider_payload_count for probe in probes) == 0
    assert sum(probe.provider_side_effect_count for probe in probes) == 0
    assert sum(probe.refusal.non_loopback_request_count for probe in probes if probe.refusal) == 0

    expected_methods = {
        SecurityControl.KILL_SWITCH: (True, False, True, False, False),
        SecurityControl.APPROVAL_BEFORE_EXECUTE: (True, True, True, False, False),
        SecurityControl.GMAIL_DRAFT_ONLY: (True, True, True, False, False),
    }
    for item in assessment.controls:
        expected = expected_methods.get(item.record.control, (True, False, True, False, True))
        assert item.record.methods.values() == expected
        assert all(type(value) is bool for value in item.record.methods.values())

    kill_switch = assessment.by_control(SecurityControl.KILL_SWITCH)
    assert kill_switch.record.relevant_output[-1] == "credentials absent"
    assert probes[3].refusal is not None
    assert probes[3].refusal.state_after is PendingActionState.PENDING
    assert probes[3].refusal.data_hashes_before == probes[3].refusal.data_hashes_after == hashes
    published = json.dumps(asdict(assessment), ensure_ascii=False, default=str)
    assert _SECRET not in published
    assert str(raw_path) not in published
    assert SensitiveCategory.SECRET.label in published
    assert SensitiveCategory.PRIVATE_PATH.label in published
    assert SensitiveCategory.PRIVATE_CONTENT.label in published


def test_missing_control_evidence_is_rejected_instead_of_reported_secure(tmp_path: Path) -> None:
    """Pin fail-closed behavior when one required control has no evidence at all."""
    probes = tuple(
        probe for probe in _all_static_probes() if probe.control is not SecurityControl.KEY_CUSTODY
    )
    with pytest.raises(ValueError, match=r"^missing security control results: key_custody$"):
        assess_security_controls(probes, _context(tmp_path))


def test_conflicting_fresh_and_historical_tiers_select_fresh_failure() -> None:
    """Pin fresh failure precedence and reject contradictory pass/fail facts as ambiguous."""
    facts = dict(
        applicability=Applicability.APPLICABLE,
        repository_search_complete=False,
        executable_path_exists=None,
        unavailable_prerequisites=(),
        execution_attempted=True,
        hardware_scope=False,
        verified_subset=(),
        aggregate_gate_failed=False,
        historical_evidence_exists=True,
        current_executable_or_claimed_path=True,
    )
    decision = decide_status(StatusDecisionFacts(complete_pass=False, failure_observed=True, **facts))
    assert decision.primary_status is AssessmentStatus.FRESH_FAILURE
    with pytest.raises(ValueError, match="complete pass cannot also report a failure"):
        StatusDecisionFacts(complete_pass=True, failure_observed=True, **facts)
    indecisive = decide_status(
        StatusDecisionFacts(complete_pass=False, failure_observed=False, **facts)
    )
    assert indecisive.primary_status is AssessmentStatus.UNVERIFIED


def test_unrecognized_refusal_condition_is_rejected_at_the_action_boundary() -> None:
    """Pin fail-closed handling instead of translating an unknown condition into refusal."""
    request = ExternalActionRequest("action-unknown", "gmail_draft", "synthetic")
    with pytest.raises((TypeError, ValueError), match="condition"):
        refuse_external_action(request, "unknown-condition", ())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ({"failure_indication": ""}, "allowed condition and observable failure"),
        ({"state_after": PendingActionState.EXECUTED}, "changed pending execution state"),
        ({"non_loopback_request_count": 1}, "provider or non-loopback address"),
        ({"loopback_fake_request_count": 0}, "fake request count does not match"),
        ({"data_hashes_after": (UserDataHash("[USER_DATA_PATH]", "0" * 64),)}, "changed pre-existing user data"),
    ),
)
def test_forged_reassuring_refusal_observations_are_rejected(
    change: dict[str, object], message: str
) -> None:
    """Pin every refusal boundary that could otherwise turn unsafe state into a pass."""
    hashes = (UserDataHash("[USER_DATA_PATH]", sha256(b"before").hexdigest()),)
    valid = refuse_external_action(
        ExternalActionRequest("action", "gmail_draft", "synthetic"),
        RefusalCondition.REJECTING_LOOPBACK_FAKE,
        hashes,
    )
    with pytest.raises(ValueError, match=message):
        SecurityProbeResult(
            control=SecurityControl.GMAIL_DRAFT_ONLY,
            mode=SecurityProbeMode.HERMETIC_EXECUTION,
            complete_scope=False,
            refusal=replace(valid, **change),
        )
