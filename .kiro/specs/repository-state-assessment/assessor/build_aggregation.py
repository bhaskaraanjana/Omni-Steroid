"""Pure fail-closed aggregation for required Product Build components."""

from __future__ import annotations

from dataclasses import dataclass

from .model_types import AssessmentStatus, require_primary_status


@dataclass(frozen=True, slots=True)
class BuildComponentResult:
    """The separate observed result for one applicable required component."""

    component_id: str
    executed: bool
    passed: bool | None
    primary_status: AssessmentStatus | None = None

    def __post_init__(self) -> None:
        """Reject identifiers or statuses inconsistent with observed execution."""
        if not self.component_id:
            raise ValueError("component_id must not be empty")
        if self.passed is not None and not self.executed:
            raise ValueError("a passing or failing result requires component execution")
        if self.primary_status is None:
            return
        require_primary_status(self.primary_status)
        if self.passed is True and self.primary_status is not AssessmentStatus.VERIFIED_WORKING:
            raise ValueError("a passing component must be Verified_Working")
        if self.passed is False and self.primary_status is not AssessmentStatus.FRESH_FAILURE:
            raise ValueError("a failed build component must be Fresh_Failure")
        if not self.executed and self.primary_status in {
            AssessmentStatus.VERIFIED_WORKING,
            AssessmentStatus.FRESH_FAILURE,
            AssessmentStatus.INTEGRATION_FAILED,
        }:
            raise ValueError("an unexecuted component cannot have a fresh result")

    @property
    def effective_status(self) -> AssessmentStatus:
        """Return the explicit component status or derive it from execution."""
        if self.primary_status is not None:
            return self.primary_status
        if self.passed is True:
            return AssessmentStatus.VERIFIED_WORKING
        if self.passed is False:
            return AssessmentStatus.FRESH_FAILURE
        return AssessmentStatus.UNVERIFIED


@dataclass(frozen=True, slots=True)
class AggregateBuildResult:
    """Aggregate status plus every unchanged component-level result and gap."""

    primary_status: AssessmentStatus
    component_records: tuple[BuildComponentResult, ...]
    missing_component_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        """Enforce the single-status contract on the aggregate gate."""
        require_primary_status(self.primary_status)

    @property
    def product_failure_component_ids(self) -> tuple[str, ...]:
        """Return executed failures while excluding blocked component checks."""
        return tuple(
            record.component_id
            for record in self.component_records
            if record.effective_status is AssessmentStatus.FRESH_FAILURE
        )


def aggregate_product_build(
    required_component_ids: tuple[str, ...],
    component_records: tuple[BuildComponentResult, ...],
) -> AggregateBuildResult:
    """Aggregate required components fail-closed while retaining every child result."""
    if not required_component_ids:
        raise ValueError("at least one applicable required component is required")
    if len(set(required_component_ids)) != len(required_component_ids):
        raise ValueError("required component identifiers must be unique")

    required_ids = set(required_component_ids)
    record_ids = tuple(record.component_id for record in component_records)
    if len(set(record_ids)) != len(record_ids):
        raise ValueError("component records must have unique identifiers")
    if set(record_ids) - required_ids:
        raise ValueError("component records must belong to the required component set")

    recorded_ids = set(record_ids)
    missing_ids = tuple(
        component_id
        for component_id in required_component_ids
        if component_id not in recorded_ids
    )
    statuses = tuple(record.effective_status for record in component_records)

    if AssessmentStatus.FRESH_FAILURE in statuses:
        status = AssessmentStatus.FRESH_FAILURE
    elif missing_ids or any(item is not AssessmentStatus.VERIFIED_WORKING for item in statuses):
        status = AssessmentStatus.UNVERIFIED
    else:
        status = AssessmentStatus.VERIFIED_WORKING

    return AggregateBuildResult(status, component_records, missing_ids)
