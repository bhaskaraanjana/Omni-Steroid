"""Build complete EvidenceRecord objects for admitted security observations.

Evidence construction is separate from probe admission so sanitized output is the only
text eligible for permanent records. No raw provider-adjacent payload is retained.
"""

from __future__ import annotations

from .evidence_models import EvidenceRecord, RerunInstruction, TestCounts
from .execution_models import Applicability, Prerequisite, Termination, TerminationKind
from .model_types import ProcessOwnership, VerificationPlane
from .security_records import SecurityRecord
from .status_decision import StatusDecisionFacts, decide_status


def build_security_evidence(probe, record: SecurityRecord, context) -> EvidenceRecord:
    """Create one referentially complete evidence record for a sanitized control."""
    decision = decide_status(
        StatusDecisionFacts(
            applicability=Applicability.APPLICABLE,
            repository_search_complete=False,
            executable_path_exists=None,
            unavailable_prerequisites=probe.unavailable_prerequisites,
            execution_attempted=probe.execution_attempted,
            hardware_scope=False,
            complete_pass=probe.complete_scope,
            verified_subset=(),
            failure_observed=probe.failure_observed,
            aggregate_gate_failed=False,
            historical_evidence_exists=False,
            current_executable_or_claimed_path=True,
        )
    )
    prerequisites = tuple(
        Prerequisite(
            name=name,
            detection_procedure=(f"Confirm local prerequisite: {name}",),
            available=False,
            evidence_ref=f"security-preflight-{record.control.value}",
        )
        for name in probe.unavailable_prerequisites
    )
    termination = _termination_for(probe)
    procedure = _procedure_for(probe)
    ownership = probe.process_ownership or ProcessOwnership(
        f"security-{record.control.value}-no-process",
        "static inspection" if probe.mode.value == "static_inspection" else "no process launched",
        (),
        True,
    )
    return EvidenceRecord(
        evidence_id=f"security-{record.control.value}",
        check_id=f"security-{record.control.value}",
        plane=VerificationPlane.SECURITY_PRIVACY,
        scope=record.control.value,
        exact_argv=None,
        numbered_procedure=procedure,
        source_command_locations=probe.source_locations,
        cwd=context.cwd,
        started_at=context.started_at,
        duration_ms=probe.duration_ms,
        termination=termination,
        prerequisites=prerequisites,
        environment=context.environment,
        source_revision=context.source_revision,
        stdout_ref=None,
        stderr_ref=None,
        relevant_output=record.relevant_output,
        warnings=(),
        test_counts=TestCounts(),
        measurements=(),
        artifacts=(),
        network_observation_ref=probe.network_observation_ref,
        process_ownership=ownership,
        write_audit_ref=probe.write_audit_ref,
        primary_status=decision.primary_status,
        status_basis=decision.status_basis,
        rerun=RerunInstruction(
            prerequisites=probe.unavailable_prerequisites,
            exact_argv=None,
            numbered_procedure=procedure,
            expected_observable=_expected_observable(decision.primary_status, record),
        ),
    )


def _termination_for(probe) -> Termination:
    if probe.unavailable_prerequisites and not probe.execution_attempted:
        return Termination(TerminationKind.PRECHECK_BLOCKED)
    if not probe.execution_attempted:
        return Termination(TerminationKind.OMITTED)
    return Termination(TerminationKind.EXITED, exit_code=1 if probe.failure_observed else 0)


def _procedure_for(probe) -> tuple[str, ...]:
    if probe.mode.value == "static_inspection":
        return (
            f"Inspect repository source and tests for {probe.control.value}.",
            "Record only source locations and category-redacted findings; execute no product code.",
        )
    return (
        f"Create disposable local state for {probe.control.value}.",
        "Start with a fresh allowlisted environment that does not inherit credentials.",
        "Use synthetic non-private input and absent credentials or a rejecting loopback fake.",
        "Deny non-loopback traffic and verify zero provider calls, payloads, and side effects.",
        "Verify refusal state and user-data hashes, then clean only assessment-owned processes.",
    )


def _expected_observable(status, record: SecurityRecord) -> str:
    return (
        f"{record.control.value} produces {status.value} with five verification-method booleans, "
        "zero provider calls or payloads, and only category-redacted permanent output"
    )
