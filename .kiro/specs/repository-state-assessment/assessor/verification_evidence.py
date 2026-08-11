"""Pure construction of one fresh or preflight-blocked verification record."""

from __future__ import annotations

from dataclasses import dataclass

from .evidence_models import (
    AssessmentEnvironment,
    EvidenceArtifact,
    EvidenceRecord,
    RerunInstruction,
    TestCounts,
)
from .execution_models import (
    Applicability,
    CheckPlan,
    RawExecutionResult,
    Termination,
    TerminationKind,
)
from .model_types import AssessmentStatus, Measurement, ProcessOwnership, VerificationPlane, ZonedTimestamp
from .status_decision import StatusDecisionFacts, decide_status
from .summary_parser import parse_test_summary


@dataclass(frozen=True, slots=True)
class FreshVerificationEvidence:
    """Exactly one fresh process attempt or one documented preflight omission."""

    record: EvidenceRecord
    attempts: tuple[RawExecutionResult, ...]
    omission: EvidenceRecord | None

    def __post_init__(self) -> None:
        """Reject bundles that lose or duplicate the terminal verification event."""
        if len(self.attempts) + int(self.omission is not None) != 1:
            raise ValueError("evidence must contain exactly one attempt or omission")
        if self.omission is not None:
            if self.omission is not self.record:
                raise ValueError("the documented omission must be the evidence record")
            if self.record.termination.kind not in {
                TerminationKind.PRECHECK_BLOCKED,
                TerminationKind.OMITTED,
            }:
                raise ValueError("an omission must have an omitted termination kind")
        elif self.attempts[0].check_id != self.record.check_id:
            raise ValueError("attempt and evidence check identifiers must match")


def normalize_fresh_verification(
    *,
    plan: CheckPlan,
    assessment_started_at: ZonedTimestamp,
    environment: AssessmentEnvironment,
    source_revision: str,
    attempt: RawExecutionResult | None,
    relevant_output: tuple[str, ...],
    warnings: tuple[str, ...] = (),
    summary_output: str | bytes | None = None,
    artifacts: tuple[EvidenceArtifact, ...] = (),
) -> FreshVerificationEvidence:
    """Create complete evidence for one bounded attempt or preflight omission."""
    if not source_revision.strip():
        raise ValueError("source_revision must be present")
    _require_non_watch(plan)

    unavailable = tuple(item for item in plan.prerequisites if item.available is False)
    if attempt is None:
        if not unavailable:
            raise ValueError("an omitted attempt requires an unavailable prerequisite")
        return _blocked_evidence(
            plan,
            assessment_started_at,
            environment,
            source_revision,
            relevant_output,
            warnings,
            unavailable,
        )

    if unavailable:
        raise ValueError("a check with unavailable prerequisites cannot execute")
    _validate_attempt(plan, assessment_started_at, attempt)
    parsed = parse_test_summary(
        summary_output if summary_output is not None else "\n".join(relevant_output),
        assessed_scope=plan.scope,
    )
    normalized_warnings = tuple(dict.fromkeys((*warnings, *parsed.warnings)))
    status, basis = _status_for(attempt.termination, plan.plane)
    record = _record(
        plan=plan,
        environment=environment,
        source_revision=source_revision,
        started_at=attempt.started_at,
        duration_ms=attempt.duration_ms,
        termination=attempt.termination,
        stdout_ref=attempt.stdout_ref,
        stderr_ref=attempt.stderr_ref,
        relevant_output=relevant_output,
        warnings=normalized_warnings,
        process_ownership=attempt.process_ownership,
        write_audit_ref=attempt.write_audit_ref,
        network_observation_ref=attempt.network_observation_ref,
        status=status,
        status_basis=basis,
        test_counts=parsed.test_counts,
        measurements=parsed.measurements,
        artifacts=artifacts,
    )
    return FreshVerificationEvidence(record, (attempt,), None)


def _blocked_evidence(
    plan: CheckPlan,
    started_at: ZonedTimestamp,
    environment: AssessmentEnvironment,
    source_revision: str,
    relevant_output: tuple[str, ...],
    warnings: tuple[str, ...],
    unavailable: tuple,
) -> FreshVerificationEvidence:
    blocker_text = tuple(f"unavailable prerequisite: {item.name}" for item in unavailable)
    record = _record(
        plan=plan,
        environment=environment,
        source_revision=source_revision,
        started_at=started_at,
        duration_ms=0,
        termination=Termination(
            TerminationKind.PRECHECK_BLOCKED,
            exit_code=None,
            signal=None,
            timeout_ms=plan.timeout_ms,
        ),
        stdout_ref=None,
        stderr_ref=None,
        relevant_output=relevant_output + blocker_text,
        warnings=warnings,
        process_ownership=ProcessOwnership(
            ownership_token=f"preflight-{plan.check_id}",
            mechanism="documented-preflight-omission",
            processes=(),
            cleanup_completed=True,
        ),
        write_audit_ref=None,
        network_observation_ref=None,
        status=AssessmentStatus.ENVIRONMENT_BLOCKED,
        status_basis="named prerequisite unavailable before execution",
    )
    return FreshVerificationEvidence(record, (), record)


def _record(
    *,
    plan: CheckPlan,
    environment: AssessmentEnvironment,
    source_revision: str,
    started_at: ZonedTimestamp,
    duration_ms: int,
    termination: Termination,
    stdout_ref: str | None,
    stderr_ref: str | None,
    relevant_output: tuple[str, ...],
    warnings: tuple[str, ...],
    process_ownership: ProcessOwnership,
    write_audit_ref: str | None,
    network_observation_ref: str | None,
    status: AssessmentStatus,
    status_basis: str,
    test_counts: TestCounts = TestCounts(),
    measurements: tuple[Measurement, ...] = (),
    artifacts: tuple[EvidenceArtifact, ...] = (),
) -> EvidenceRecord:
    source_locations = (
        (plan.command_source.location,) if plan.command_source is not None else ()
    )
    rerun = RerunInstruction(
        prerequisites=tuple(item.name for item in plan.prerequisites),
        exact_argv=plan.exact_argv,
        numbered_procedure=plan.numbered_procedure,
        expected_observable="one terminating non-watch result with captured output",
    )
    return EvidenceRecord(
        evidence_id=f"evidence-{plan.check_id}",
        check_id=plan.check_id,
        plane=plan.plane,
        scope=plan.scope,
        exact_argv=plan.exact_argv,
        numbered_procedure=plan.numbered_procedure,
        source_command_locations=source_locations,
        cwd=plan.cwd,
        started_at=started_at,
        duration_ms=duration_ms,
        termination=termination,
        prerequisites=plan.prerequisites,
        environment=environment,
        source_revision=source_revision,
        stdout_ref=stdout_ref,
        stderr_ref=stderr_ref,
        relevant_output=relevant_output,
        warnings=warnings,
        test_counts=test_counts,
        measurements=measurements,
        artifacts=artifacts,
        network_observation_ref=network_observation_ref,
        process_ownership=process_ownership,
        write_audit_ref=write_audit_ref,
        primary_status=status,
        status_basis=status_basis,
        rerun=rerun,
    )


def _validate_attempt(
    plan: CheckPlan,
    assessment_started_at: ZonedTimestamp,
    attempt: RawExecutionResult,
) -> None:
    if attempt.check_id != plan.check_id:
        raise ValueError("attempt check_id does not match its plan")
    if attempt.exact_argv != plan.exact_argv:
        raise ValueError("attempt argv does not match its plan")
    if attempt.numbered_procedure != plan.numbered_procedure:
        raise ValueError("attempt procedure does not match its plan")
    if attempt.cwd != plan.cwd:
        raise ValueError("attempt cwd does not match its plan")
    if attempt.started_at.value < assessment_started_at.value:
        raise ValueError("attempt was not started during the current assessment")
    if attempt.duration_ms > plan.timeout_ms:
        raise ValueError("attempt exceeded its declared bound")
    if attempt.termination.timeout_ms != plan.timeout_ms:
        raise ValueError("attempt did not retain its declared timeout")
    if attempt.termination.kind in {
        TerminationKind.PRECHECK_BLOCKED,
        TerminationKind.OMITTED,
    }:
        raise ValueError("a preflight omission is not a process attempt")
    if not attempt.process_ownership.processes:
        raise ValueError("a process attempt must retain fresh process identity")
    if not attempt.process_ownership.cleanup_completed:
        raise ValueError("a terminating attempt must complete owned-process cleanup")
    if any(
        process.created_at.value < assessment_started_at.value
        for process in attempt.process_ownership.processes
    ):
        raise ValueError("attempt reused a process from before the assessment")

    exited = attempt.termination.kind is TerminationKind.EXITED
    if exited != (attempt.termination.exit_code is not None):
        raise ValueError("only exited attempts may have an exit code")


def _status_for(
    termination: Termination, plane: VerificationPlane
) -> tuple[AssessmentStatus, str]:
    supported = {
        TerminationKind.EXITED,
        TerminationKind.TIMED_OUT,
        TerminationKind.CANCELLED,
        TerminationKind.CRASHED,
    }
    if termination.kind not in supported:
        raise ValueError("unsupported attempted-command termination")

    passed = termination.kind is TerminationKind.EXITED and termination.exit_code == 0
    failed = termination.kind in {
        TerminationKind.TIMED_OUT,
        TerminationKind.CRASHED,
    } or (termination.kind is TerminationKind.EXITED and termination.exit_code != 0)
    decision = decide_status(
        StatusDecisionFacts(
            applicability=Applicability.APPLICABLE,
            repository_search_complete=False,
            executable_path_exists=True,
            unavailable_prerequisites=(),
            execution_attempted=True,
            hardware_scope=plane is VerificationPlane.HARDWARE_INTEGRATION,
            complete_pass=passed,
            verified_subset=(),
            failure_observed=failed,
            aggregate_gate_failed=False,
            historical_evidence_exists=False,
            current_executable_or_claimed_path=True,
        )
    )
    return decision.primary_status, decision.status_basis


def _require_non_watch(plan: CheckPlan) -> None:
    watch_tokens = {"watch", "--watch", "--watch=true", "-w"}
    if plan.exact_argv is not None:
        tokens = {token.strip().lower() for token in plan.exact_argv.values[1:]}
        if tokens & watch_tokens:
            raise ValueError("verification commands must be non-watch")
    elif plan.numbered_procedure is not None and any(
        "--watch" in step.lower() or "watch mode" in step.lower()
        for step in plan.numbered_procedure
    ):
        raise ValueError("verification procedures must be non-watch")
