"""Property 5 coverage for fresh, bounded, evidence-complete verification."""

from __future__ import annotations

import random
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from assessor import (
    Applicability,
    AssessmentEnvironment,
    AssessmentStatus,
    CheckPlan,
    CommandSource,
    ExactArgumentVector,
    HardwareInventory,
    NetworkMode,
    NetworkPolicy,
    OperatingSystemInventory,
    OwnedProcess,
    Prerequisite,
    ProcessOwnership,
    RawExecutionResult,
    SourceLocation,
    Termination,
    TerminationKind,
    ToolVersion,
    VerificationPlane,
    WritePolicy,
    ZonedTimestamp,
)
from assessor.evidence_models import EvidenceRecord
from assessor.verification_evidence import normalize_fresh_verification

_SEED = 20260708
_CASES = 150


class Scenario(StrEnum):
    PASS = "pass"
    NONZERO = "nonzero"
    TIMEOUT = "timeout"
    ABORT = "abort"
    PREFLIGHT_BLOCK = "preflight_block"


def _environment(case: int) -> AssessmentEnvironment:
    return AssessmentEnvironment(
        operating_system=OperatingSystemInventory("Windows", "11", "26100"),
        hardware=(HardwareInventory("cpu", f"fixture-cpu-{case}"),),
        tool_versions=(ToolVersion("fixture-python", "3.11", "python.exe"),),
        safe_variable_names=("PYTHONUTF8", "TEMP"),
    )


def _plan(case: int, timeout_ms: int, blocked: bool) -> CheckPlan:
    prerequisite = Prerequisite(
        name=f"fixture-tool-{case}",
        detection_procedure=("resolve executable", "record version"),
        available=not blocked,
        evidence_ref=f"preflight/{case}.json",
    )
    return CheckPlan(
        check_id=f"check-{case}",
        plane=VerificationPlane.PYTHON_ENGINE,
        scope=f"generated verification {case}",
        command_source=CommandSource(
            SourceLocation("Makefile", 10 + case, 10 + case), f"{case:064x}"[-64:]
        ),
        exact_argv=ExactArgumentVector(
            ("python.exe", "-c", f"raise SystemExit({case % 7})")
        ),
        numbered_procedure=None,
        cwd=f"C:\\assessment mirror\\case {case}",
        prerequisites=(prerequisite,),
        applicability=Applicability.APPLICABLE,
        applicability_basis="generated applicable check",
        timeout_ms=timeout_ms,
        write_policy=WritePolicy((f"C:\\assessment-run\\{case}",)),
        network_policy=NetworkPolicy(NetworkMode.NONE),
        external_dependency=False,
        dependent_check_ids=(),
        cleanup_procedure=("close owned job object",),
    )


def _attempt(
    case: int,
    plan: CheckPlan,
    assessment_started_at: ZonedTimestamp,
    scenario: Scenario,
    rng: random.Random,
) -> RawExecutionResult:
    started_at = ZonedTimestamp(
        assessment_started_at.value + timedelta(milliseconds=rng.randint(1, 500))
    )
    if scenario is Scenario.PASS:
        termination = Termination(TerminationKind.EXITED, 0, None, plan.timeout_ms)
    elif scenario is Scenario.NONZERO:
        exit_code = rng.choice(tuple(range(1, 10)) + (-1, -2))
        termination = Termination(
            TerminationKind.EXITED, exit_code, None, plan.timeout_ms
        )
    elif scenario is Scenario.TIMEOUT:
        termination = Termination(
            TerminationKind.TIMED_OUT, None, None, plan.timeout_ms
        )
    else:
        termination = Termination(
            TerminationKind.CANCELLED, None, rng.choice((None, 2, 15)), plan.timeout_ms
        )

    process = OwnedProcess(
        pid=1000 + case,
        created_at=started_at,
        executable="python.exe",
    )
    return RawExecutionResult(
        check_id=plan.check_id,
        exact_argv=plan.exact_argv,
        numbered_procedure=None,
        cwd=plan.cwd,
        started_at=started_at,
        duration_ms=rng.randint(0, plan.timeout_ms),
        termination=termination,
        stdout_ref=f"raw/{case}.stdout",
        stderr_ref=f"raw/{case}.stderr",
        process_ownership=ProcessOwnership(
            f"ownership-{case}", "job-object", (process,), True
        ),
        write_audit_ref=f"audit/{case}.json",
        network_observation_ref=f"network/{case}.json",
    )


def _normalize_case(case: int, scenario: Scenario, rng: random.Random):
    offset = timezone(timedelta(minutes=rng.choice((-480, 0, 330, 600))))
    assessment_started_at = ZonedTimestamp(
        datetime(2026, 7, 8, 9, case % 60, tzinfo=offset)
    )
    timeout_ms = rng.randint(1, 120_000)
    blocked = scenario is Scenario.PREFLIGHT_BLOCK
    plan = _plan(case, timeout_ms, blocked)
    attempt = (
        None
        if blocked
        else _attempt(case, plan, assessment_started_at, scenario, rng)
    )
    result = normalize_fresh_verification(
        plan=plan,
        assessment_started_at=assessment_started_at,
        environment=_environment(case),
        source_revision=f"{case + 1:040x}"[-40:],
        attempt=attempt,
        relevant_output=(
            f"generated {scenario.value} output for case {case}",
        ),
        warnings=(f"warning-{case}",) if case % 11 == 0 else (),
    )
    return assessment_started_at, plan, attempt, result


def test_pass_example_is_one_fresh_complete_attempt() -> None:
    """A passing command produces one fresh attempt and no omission."""
    started, plan, attempt, result = _normalize_case(
        0, Scenario.PASS, random.Random(_SEED)
    )

    assert attempt is not None
    assert result.attempts == (attempt,)
    assert result.omission is None
    assert result.record.started_at.value >= started.value
    assert result.record.termination.exit_code == 0
    assert result.record.primary_status is AssessmentStatus.VERIFIED_WORKING
    assert result.record.rerun.exact_argv == plan.exact_argv


def test_fresh_bounded_evidence_records_property() -> None:
    """Property 5: verification planning is fresh, bounded, and evidence-complete.

    **Validates: Requirements 3.1, 3.13, 3.14, 3.15**
    """
    rng = random.Random(_SEED)
    scenarios = tuple(Scenario)
    seen: set[Scenario] = set()
    required_fields = {field.name for field in fields(EvidenceRecord)}

    for case in range(_CASES):
        scenario = scenarios[case % len(scenarios)]
        assessment_started_at, plan, attempt, result = _normalize_case(
            case, scenario, rng
        )
        record = result.record
        seen.add(scenario)

        assert len(result.attempts) + int(result.omission is not None) == 1
        assert {field.name for field in fields(record)} == required_fields
        assert record.evidence_id and record.check_id == plan.check_id
        assert record.plane is plan.plane and record.scope == plan.scope
        assert (record.exact_argv is None) != (record.numbered_procedure is None)
        assert record.source_command_locations == (plan.command_source.location,)
        assert record.cwd == plan.cwd
        assert record.started_at.value >= assessment_started_at.value
        assert 0 <= record.duration_ms <= plan.timeout_ms
        assert record.termination.timeout_ms == plan.timeout_ms
        assert record.prerequisites == plan.prerequisites
        assert record.environment.operating_system.name
        assert record.environment.tool_versions
        assert record.source_revision
        assert record.relevant_output
        assert record.status_basis
        assert record.rerun.prerequisites
        assert record.rerun.exact_argv == plan.exact_argv
        assert record.rerun.numbered_procedure is None
        assert record.rerun.expected_observable

        if scenario is Scenario.PREFLIGHT_BLOCK:
            assert attempt is None
            assert result.attempts == ()
            assert result.omission is record
            assert record.termination.kind is TerminationKind.PRECHECK_BLOCKED
            assert record.termination.exit_code is None
            assert record.primary_status is AssessmentStatus.ENVIRONMENT_BLOCKED
            assert not record.process_ownership.processes
            assert all(item.available is False for item in record.prerequisites)
        else:
            assert attempt is not None
            assert result.attempts == (attempt,)
            assert result.omission is None
            assert record.process_ownership.processes
            assert record.process_ownership.ownership_token
            assert record.process_ownership.cleanup_completed
            assert record.stdout_ref and record.stderr_ref
            assert record.termination.kind in {
                TerminationKind.EXITED,
                TerminationKind.TIMED_OUT,
                TerminationKind.CANCELLED,
            }
            if scenario is Scenario.PASS:
                assert record.primary_status is AssessmentStatus.VERIFIED_WORKING
            elif scenario in {Scenario.NONZERO, Scenario.TIMEOUT}:
                assert record.primary_status is AssessmentStatus.FRESH_FAILURE
            else:
                assert record.primary_status is AssessmentStatus.UNVERIFIED

    assert _CASES >= 100
    assert seen == set(Scenario)
