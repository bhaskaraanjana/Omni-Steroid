"""Unit examples for evidence normalization and deterministic status decisions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from assessor.baseline_models import HardwareInventory, OperatingSystemInventory, ToolVersion
from assessor.build_aggregation import BuildComponentResult, aggregate_product_build
from assessor.evidence_models import AssessmentEnvironment, EvidenceArtifact, TestCounts
from assessor.execution_models import (
    Applicability,
    CheckPlan,
    CommandSource,
    Prerequisite,
    RawExecutionResult,
    Termination,
    TerminationKind,
)
from assessor.model_types import (
    AssessmentStatus,
    ExactArgumentVector,
    Measurement,
    MeasurementUnit,
    NetworkMode,
    NetworkPolicy,
    OwnedProcess,
    ProcessOwnership,
    SourceLocation,
    VerificationPlane,
    WritePolicy,
    ZonedTimestamp,
)
from assessor.status_decision import StatusDecisionFacts, decide_status, is_product_failure
from assessor.summary_parser import evaluate_python_coverage
from assessor.verification_evidence import normalize_fresh_verification


def _started_at() -> ZonedTimestamp:
    return ZonedTimestamp(datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc))


def _environment() -> AssessmentEnvironment:
    return AssessmentEnvironment(
        OperatingSystemInventory("Windows", "11", "26100"),
        (HardwareInventory("cpu", "fixture"),),
        (ToolVersion("pytest", "9.0", "pytest.exe"),),
        ("PYTHONUTF8",),
    )


def _plan(*, blocked: bool = False) -> CheckPlan:
    return CheckPlan(
        check_id="python-tests",
        plane=VerificationPlane.PYTHON_ENGINE,
        scope="Python test and coverage verification",
        command_source=CommandSource(SourceLocation("Makefile", 10, 10), "a" * 64),
        exact_argv=ExactArgumentVector(("pytest.exe", "--cov")),
        numbered_procedure=None,
        cwd=r"C:\assessment mirror",
        prerequisites=(
            Prerequisite(
                "pytest",
                ("resolve pytest",),
                available=not blocked,
                evidence_ref="preflight/pytest.json",
            ),
        ),
        applicability=Applicability.APPLICABLE,
        applicability_basis="configured Python verification",
        timeout_ms=30_000,
        write_policy=WritePolicy((r"C:\assessment run",)),
        network_policy=NetworkPolicy(NetworkMode.NONE),
        external_dependency=False,
        dependent_check_ids=(),
        cleanup_procedure=("close job",),
    )


def _attempt(plan: CheckPlan) -> RawExecutionResult:
    started = _started_at()
    return RawExecutionResult(
        check_id=plan.check_id,
        exact_argv=plan.exact_argv,
        numbered_procedure=None,
        cwd=plan.cwd,
        started_at=started,
        duration_ms=1_234,
        termination=Termination(TerminationKind.EXITED, 0, None, plan.timeout_ms),
        stdout_ref="raw/pytest.stdout",
        stderr_ref="raw/pytest.stderr",
        process_ownership=ProcessOwnership(
            "owned-python-tests",
            "job-object",
            (OwnedProcess(101, started, "pytest.exe"),),
            True,
        ),
        write_audit_ref="audit/python-tests.json",
        network_observation_ref="network/python-tests.json",
    )


def test_executed_evidence_normalizes_counts_coverage_warnings_and_artifacts() -> None:
    plan = _plan()
    summary = (
        "7 passed, 2 failed, 3 skipped, 4 deselected, 5 ignored, 2 warnings\n"
        "Lines: 89.9% | Branches: 85.0%\n"
        "WARNING: first detail\n[warning]: second detail"
    )
    artifacts = (EvidenceArtifact("coverage_json", "artifacts/coverage.json"),)

    evidence = normalize_fresh_verification(
        plan=plan,
        assessment_started_at=_started_at(),
        environment=_environment(),
        source_revision="b" * 40,
        attempt=_attempt(plan),
        relevant_output=("pytest summary retained",),
        summary_output=summary,
        artifacts=artifacts,
    ).record

    assert evidence.duration_ms == 1_234
    assert evidence.test_counts == TestCounts(7, 2, 3, 4, 5)
    assert evidence.warnings == ("first detail", "second detail")
    assert {item.name: item.value for item in evidence.measurements} == {
        "lines_coverage": Decimal("89.9"),
        "branches_coverage": Decimal("85.0"),
    }
    assert evidence.artifacts == artifacts


def test_blocked_record_is_complete_and_not_a_product_failure() -> None:
    record = normalize_fresh_verification(
        plan=_plan(blocked=True),
        assessment_started_at=_started_at(),
        environment=_environment(),
        source_revision="c" * 40,
        attempt=None,
        relevant_output=("pytest executable was not found",),
    ).record

    assert record.primary_status is AssessmentStatus.ENVIRONMENT_BLOCKED
    assert record.test_counts == TestCounts()
    assert record.measurements == ()
    assert record.artifacts == ()
    assert record.rerun.prerequisites == ("pytest",)
    assert not is_product_failure(record.primary_status)


def test_python_line_and_branch_targets_are_compared_independently() -> None:
    decisions = evaluate_python_coverage(
        (
            Measurement("lines_coverage", Decimal("89.9"), MeasurementUnit.PERCENT, "Python"),
            Measurement("branches_coverage", Decimal("85.0"), MeasurementUnit.PERCENT, "Python"),
        )
    )

    assert [(item.dimension, item.target, item.meets_target) for item in decisions] == [
        ("lines", Decimal("90"), False),
        ("branches", Decimal("85"), True),
    ]


def test_status_decision_order_is_deterministic() -> None:
    base = StatusDecisionFacts(
        applicability=Applicability.APPLICABLE,
        repository_search_complete=False,
        executable_path_exists=True,
        unavailable_prerequisites=(),
        execution_attempted=False,
        hardware_scope=False,
        complete_pass=False,
        verified_subset=(),
        failure_observed=False,
        aggregate_gate_failed=False,
        historical_evidence_exists=False,
        current_executable_or_claimed_path=True,
    )

    assert decide_status(replace(base, applicability=Applicability.NOT_APPLICABLE)).primary_status is AssessmentStatus.NOT_APPLICABLE
    assert decide_status(replace(base, repository_search_complete=True, executable_path_exists=False, unavailable_prerequisites=("tool",), historical_evidence_exists=True)).primary_status is AssessmentStatus.NOT_IMPLEMENTED
    blocked = decide_status(replace(base, unavailable_prerequisites=("tool",)))
    assert blocked.primary_status is AssessmentStatus.ENVIRONMENT_BLOCKED
    assert not blocked.counts_as_product_failure
    assert decide_status(replace(base, execution_attempted=True, complete_pass=True)).primary_status is AssessmentStatus.VERIFIED_WORKING
    assert decide_status(replace(base, execution_attempted=True, verified_subset=("unit",), failure_observed=True)).primary_status is AssessmentStatus.VERIFIED_PARTIAL
    assert decide_status(replace(base, execution_attempted=True, failure_observed=True)).primary_status is AssessmentStatus.FRESH_FAILURE
    assert decide_status(replace(base, execution_attempted=True, hardware_scope=True, failure_observed=True)).primary_status is AssessmentStatus.INTEGRATION_FAILED
    assert decide_status(replace(base, historical_evidence_exists=True)).primary_status is AssessmentStatus.HISTORICAL_ONLY
    assert decide_status(base).primary_status is AssessmentStatus.UNVERIFIED


def test_build_aggregation_retains_blocked_component_without_counting_failure() -> None:
    records = (
        BuildComponentResult("engine", True, True),
        BuildComponentResult(
            "desktop",
            False,
            None,
            primary_status=AssessmentStatus.ENVIRONMENT_BLOCKED,
        ),
    )

    aggregate = aggregate_product_build(("engine", "desktop"), records)

    assert aggregate.primary_status is AssessmentStatus.UNVERIFIED
    assert aggregate.product_failure_component_ids == ()
    assert aggregate.component_records == records
