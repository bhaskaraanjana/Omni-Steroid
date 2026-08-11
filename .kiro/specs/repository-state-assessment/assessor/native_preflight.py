"""Pure preflight resolution for inert hardware/native procedure plans.

This module consumes already-observed prerequisite facts. It cannot probe a
host, open a device, launch an application, register input, or retain audio.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .evidence_models import AssessmentEnvironment
from .execution_models import CheckPlan, Prerequisite
from .model_types import ZonedTimestamp
from .native_check_plans import NativeCheckPlan
from .verification_evidence import FreshVerificationEvidence, normalize_fresh_verification


@dataclass(frozen=True, slots=True)
class NativePreflightObservation:
    """One non-behavioral prerequisite observation with detection evidence."""

    prerequisite_name: str
    available: bool
    detection_evidence: str
    detection_detail: str
    scoped_behavior_executed: bool = False

    def __post_init__(self) -> None:
        if not all(
            (self.prerequisite_name, self.detection_evidence, self.detection_detail)
        ):
            raise ValueError("preflight observations require name and detection evidence")


@dataclass(frozen=True, slots=True)
class NativePreflightResult:
    """Resolved admission facts or one complete Environment_Blocked record."""

    native_plan: NativeCheckPlan
    resolved_plan: CheckPlan
    observations: tuple[NativePreflightObservation, ...]
    ready_for_scoped_behavior: bool
    blocked_evidence: FreshVerificationEvidence | None

    def __post_init__(self) -> None:
        if self.ready_for_scoped_behavior == (self.blocked_evidence is not None):
            raise ValueError("ready preflights cannot also contain blocked evidence")


def preflight_native_check(
    *,
    plan: NativeCheckPlan,
    observations: tuple[NativePreflightObservation, ...],
    started_at: ZonedTimestamp,
    environment: AssessmentEnvironment,
    source_revision: str,
) -> NativePreflightResult:
    """Resolve an exact preflight set without running the planned procedure."""
    if any(item.scoped_behavior_executed for item in observations):
        raise ValueError("preflight must not execute scoped behavior")
    expected_names = tuple(item.name for item in plan.check_plan.prerequisites)
    observed_names = tuple(item.prerequisite_name for item in observations)
    if len(set(observed_names)) != len(observed_names) or set(observed_names) != set(
        expected_names
    ):
        raise ValueError("preflight observations must cover prerequisites exactly once")

    by_name = {item.prerequisite_name: item for item in observations}
    ordered = tuple(by_name[name] for name in expected_names)
    resolved_prerequisites = tuple(
        Prerequisite(
            name=prior.name,
            detection_procedure=prior.detection_procedure,
            available=observation.available,
            evidence_ref=observation.detection_evidence,
        )
        for prior, observation in zip(
            plan.check_plan.prerequisites, ordered, strict=True
        )
    )
    resolved = replace(plan.check_plan, prerequisites=resolved_prerequisites)
    unavailable = tuple(item for item in ordered if not item.available)
    if not unavailable:
        return NativePreflightResult(plan, resolved, ordered, True, None)

    output = tuple(
        f"preflight {item.prerequisite_name}: "
        f"{'available' if item.available else 'unavailable'}; {item.detection_detail}"
        for item in ordered
    )
    blocked = normalize_fresh_verification(
        plan=resolved,
        assessment_started_at=started_at,
        environment=environment,
        source_revision=source_revision,
        attempt=None,
        relevant_output=output,
    )
    return NativePreflightResult(plan, resolved, ordered, False, blocked)
