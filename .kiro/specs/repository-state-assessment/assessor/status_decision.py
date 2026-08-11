"""Deterministic primary-status decisions for assessed non-claim scopes.

The ordering mirrors the design decision table and keeps unavailable prerequisites
separate from product failures. Documentary precedence remains in evidence_precedence.
"""

from __future__ import annotations

from dataclasses import dataclass

from .execution_models import Applicability
from .model_types import AssessmentStatus, require_primary_status


_PRODUCT_FAILURE_STATUSES = frozenset(
    {AssessmentStatus.FRESH_FAILURE, AssessmentStatus.INTEGRATION_FAILED}
)


@dataclass(frozen=True, slots=True)
class StatusDecisionFacts:
    """Evidence predicates used to select exactly one primary status."""

    applicability: Applicability
    repository_search_complete: bool
    executable_path_exists: bool | None
    unavailable_prerequisites: tuple[str, ...]
    execution_attempted: bool
    hardware_scope: bool
    complete_pass: bool
    verified_subset: tuple[str, ...]
    failure_observed: bool
    aggregate_gate_failed: bool
    historical_evidence_exists: bool
    current_executable_or_claimed_path: bool

    def __post_init__(self) -> None:
        """Reject contradictory fresh-result and search predicates."""
        if not isinstance(self.applicability, Applicability):
            raise TypeError("applicability must be one Applicability value")
        if self.complete_pass and (self.failure_observed or self.aggregate_gate_failed):
            raise ValueError("a complete pass cannot also report a failure")
        if self.aggregate_gate_failed and not self.execution_attempted:
            raise ValueError("an aggregate gate cannot fail without execution")
        if self.verified_subset and not self.execution_attempted:
            raise ValueError("a verified subset requires fresh execution")
        if self.repository_search_complete and self.executable_path_exists is None:
            raise ValueError("a completed repository search requires a path conclusion")
        if any(not item for item in self.unavailable_prerequisites):
            raise ValueError("unavailable prerequisite names must not be empty")


@dataclass(frozen=True, slots=True)
class StatusDecision:
    """One deterministic primary status plus its auditable decision basis."""

    primary_status: AssessmentStatus
    status_basis: str
    verified_subset: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Enforce the enum-valued single-primary-status contract."""
        require_primary_status(self.primary_status)
        if not self.status_basis:
            raise ValueError("status decision requires a basis")
        if self.primary_status is not AssessmentStatus.VERIFIED_PARTIAL and self.verified_subset:
            raise ValueError("only Verified_Partial may retain a verified subset")

    @property
    def counts_as_product_failure(self) -> bool:
        """Return true only for fresh product or confirmed integration failures."""
        return is_product_failure(self.primary_status)


def is_product_failure(status: AssessmentStatus) -> bool:
    """Exclude blocked, missing, historical, and unverified checks from failures."""
    require_primary_status(status)
    return status in _PRODUCT_FAILURE_STATUSES


def decide_status(facts: StatusDecisionFacts) -> StatusDecision:
    """Apply applicability, path, blocker, fresh, and fallback rules in order."""
    if facts.applicability is Applicability.NOT_APPLICABLE:
        return StatusDecision(
            AssessmentStatus.NOT_APPLICABLE,
            "scope does not apply to the assessed host or configuration",
        )
    if facts.repository_search_complete and facts.executable_path_exists is False:
        return StatusDecision(
            AssessmentStatus.NOT_IMPLEMENTED,
            "documented complete repository search found no executable path",
        )
    if facts.unavailable_prerequisites and not facts.execution_attempted:
        blockers = ", ".join(facts.unavailable_prerequisites)
        return StatusDecision(
            AssessmentStatus.ENVIRONMENT_BLOCKED,
            f"named prerequisite unavailable before execution: {blockers}",
        )

    if facts.execution_attempted:
        if facts.complete_pass:
            return StatusDecision(
                AssessmentStatus.VERIFIED_WORKING,
                "fresh evidence passed every required behavior in the assessed scope",
            )
        if facts.hardware_scope and facts.failure_observed:
            return StatusDecision(
                AssessmentStatus.INTEGRATION_FAILED,
                "hardware prerequisite was available but fresh execution malfunctioned",
            )
        if facts.aggregate_gate_failed:
            return StatusDecision(
                AssessmentStatus.FRESH_FAILURE,
                "a required component failed the aggregate gate",
            )
        if facts.verified_subset:
            return StatusDecision(
                AssessmentStatus.VERIFIED_PARTIAL,
                "fresh evidence verified a defined proper subset",
                facts.verified_subset,
            )
        if facts.failure_observed:
            return StatusDecision(
                AssessmentStatus.FRESH_FAILURE,
                "fresh non-hardware execution failed without a passing required subset",
            )
        return StatusDecision(
            AssessmentStatus.UNVERIFIED,
            "fresh execution ended without a decisive passing or failing result",
        )

    if facts.historical_evidence_exists and facts.current_executable_or_claimed_path:
        return StatusDecision(
            AssessmentStatus.HISTORICAL_ONLY,
            "only historical evidence supports the current executable or claimed path",
        )
    return StatusDecision(
        AssessmentStatus.UNVERIFIED,
        "applicable executable or claimed scope has no adequate decisive evidence",
    )
