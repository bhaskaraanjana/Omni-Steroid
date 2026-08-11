"""Pure traceability validation and deterministic ranking for report conclusions."""

from __future__ import annotations

from dataclasses import dataclass

from .evidence_models import RerunInstruction
from .model_types import AssessmentStatus, SourceLocation, require_primary_status
from .report_models import (
    FindingCategory,
    NextActionDisposition,
    RankedFinding,
)


@dataclass(frozen=True, slots=True)
class SourceReference:
    """A source graph node that can support a report conclusion."""

    source_id: str
    location: SourceLocation


@dataclass(frozen=True, slots=True)
class CitedEvidence:
    """The rerun data required when an evidence node is cited by the report."""

    evidence_id: str
    primary_status: AssessmentStatus
    rerun: RerunInstruction
    assessment_environment: str
    unavailable_prerequisite: str | None = None
    detection_evidence: str | None = None

    def __post_init__(self) -> None:
        require_primary_status(self.primary_status)


@dataclass(frozen=True, slots=True)
class ReportConclusion:
    """A conclusion linked to one or more evidence or source graph nodes."""

    conclusion_id: str
    text: str
    evidence_refs: tuple[str, ...]
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FindingCandidate:
    """An unranked finding with explicit impact, dependencies, and completion proof."""

    finding_id: str
    category: FindingCategory
    impact: str
    impact_priority: int
    primary_status: AssessmentStatus
    evidence_refs: tuple[str, ...]
    dependency_ids: tuple[str, ...]
    disposition: NextActionDisposition
    completion_evidence_required: str

    def __post_init__(self) -> None:
        require_primary_status(self.primary_status)
        if not isinstance(self.category, FindingCategory):
            raise TypeError("finding category must be typed")
        if not isinstance(self.disposition, NextActionDisposition):
            raise TypeError("finding disposition must be exactly one typed value")
        if self.impact_priority <= 0:
            raise ValueError("finding impact priority must be positive")


@dataclass(frozen=True, slots=True)
class ActionableConclusions:
    """Resolved conclusion graph and uniquely ranked actionable findings."""

    conclusions: tuple[ReportConclusion, ...]
    evidence: tuple[CitedEvidence, ...]
    sources: tuple[SourceReference, ...]
    findings: tuple[RankedFinding, ...]


def _index_unique(items: tuple[object, ...], attribute: str, kind: str) -> dict[str, object]:
    indexed: dict[str, object] = {}
    for item in items:
        identifier = getattr(item, attribute)
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError(f"{kind} identifiers must be non-empty")
        if identifier in indexed:
            raise ValueError(f"duplicate {kind} identifier: {identifier}")
        indexed[identifier] = item
    return indexed


def _validate_evidence(item: CitedEvidence) -> None:
    if not item.assessment_environment.strip():
        raise ValueError("cited evidence requires an assessment environment")
    if not item.rerun.expected_observable.strip():
        raise ValueError("cited evidence requires an expected observable result")
    procedure = item.rerun.numbered_procedure
    if procedure is not None and (not procedure or any(not step.strip() for step in procedure)):
        raise ValueError("numbered rerun procedures require non-empty steps")
    if item.primary_status is AssessmentStatus.ENVIRONMENT_BLOCKED:
        if not item.unavailable_prerequisite:
            raise ValueError("blocked evidence requires an unavailable prerequisite")
        if not item.detection_evidence:
            raise ValueError("blocked evidence requires detection evidence")
        if item.unavailable_prerequisite not in item.rerun.prerequisites:
            raise ValueError("blocked rerun prerequisites must name the unavailable prerequisite")


def _validate_conclusions(
    conclusions: tuple[ReportConclusion, ...],
    evidence_ids: set[str],
    source_ids: set[str],
) -> None:
    for conclusion in conclusions:
        if not conclusion.text.strip():
            raise ValueError("report conclusions must not be empty")
        if not conclusion.evidence_refs and not conclusion.source_refs:
            raise ValueError("report conclusion requires evidence or a source")
        unknown_evidence = set(conclusion.evidence_refs) - evidence_ids
        unknown_sources = set(conclusion.source_refs) - source_ids
        if unknown_evidence:
            raise ValueError(f"conclusion references unknown evidence: {sorted(unknown_evidence)}")
        if unknown_sources:
            raise ValueError(f"conclusion references unknown source: {sorted(unknown_sources)}")


def _rank_findings(
    candidates: tuple[FindingCandidate, ...], evidence_ids: set[str]
) -> tuple[RankedFinding, ...]:
    candidate_index = _index_unique(candidates, "finding_id", "finding")
    typed_candidates = {
        identifier: candidate
        for identifier, candidate in candidate_index.items()
        if isinstance(candidate, FindingCandidate)
    }
    finding_ids = set(typed_candidates)
    for candidate in candidates:
        if not candidate.impact.strip():
            raise ValueError("finding impact must not be empty")
        if not candidate.completion_evidence_required.strip():
            raise ValueError("finding completion evidence must not be empty")
        if not candidate.evidence_refs:
            raise ValueError("finding requires supporting evidence")
        if set(candidate.evidence_refs) - evidence_ids:
            raise ValueError("finding references unknown evidence")
        if len(candidate.dependency_ids) != len(set(candidate.dependency_ids)):
            raise ValueError("finding dependencies must be unique")
        if candidate.finding_id in candidate.dependency_ids:
            raise ValueError("finding cannot depend on itself")
        if set(candidate.dependency_ids) - finding_ids:
            raise ValueError("finding references an unknown dependency")

    effective_priority = {
        candidate.finding_id: candidate.impact_priority for candidate in candidates
    }
    changed = True
    while changed:
        changed = False
        for candidate in candidates:
            for dependency_id in candidate.dependency_ids:
                if effective_priority[candidate.finding_id] > effective_priority[dependency_id]:
                    effective_priority[dependency_id] = effective_priority[candidate.finding_id]
                    changed = True

    remaining = set(finding_ids)
    emitted: set[str] = set()
    ordered: list[FindingCandidate] = []
    while remaining:
        ready = [
            typed_candidates[finding_id]
            for finding_id in remaining
            if set(typed_candidates[finding_id].dependency_ids) <= emitted
        ]
        if not ready:
            raise ValueError("finding dependency graph contains a cycle")
        selected = min(
            ready,
            key=lambda candidate: (-effective_priority[candidate.finding_id], candidate.finding_id),
        )
        ordered.append(selected)
        emitted.add(selected.finding_id)
        remaining.remove(selected.finding_id)

    return tuple(
        RankedFinding(
            rank=rank,
            finding_id=candidate.finding_id,
            category=candidate.category,
            impact=candidate.impact,
            primary_status=candidate.primary_status,
            evidence_refs=tuple(sorted(candidate.evidence_refs)),
            dependency_ids=tuple(sorted(candidate.dependency_ids)),
            disposition=candidate.disposition,
            completion_evidence_required=candidate.completion_evidence_required,
        )
        for rank, candidate in enumerate(ordered, start=1)
    )


def synthesize_actionable_conclusions(
    conclusions: tuple[ReportConclusion, ...],
    evidence: tuple[CitedEvidence, ...],
    sources: tuple[SourceReference, ...],
    finding_candidates: tuple[FindingCandidate, ...],
) -> ActionableConclusions:
    """Resolve report references and rank findings deterministically.

    Dependencies inherit the greatest impact of their dependents so prerequisite
    remediation remains ahead of the impacted work without losing impact priority.
    """
    conclusion_index = _index_unique(conclusions, "conclusion_id", "conclusion")
    evidence_index = _index_unique(evidence, "evidence_id", "evidence")
    source_index = _index_unique(sources, "source_id", "source")
    for item in evidence:
        _validate_evidence(item)
    _validate_conclusions(conclusions, set(evidence_index), set(source_index))
    findings = _rank_findings(finding_candidates, set(evidence_index))
    return ActionableConclusions(
        conclusions=tuple(conclusion_index[key] for key in sorted(conclusion_index)),  # type: ignore[misc]
        evidence=tuple(evidence_index[key] for key in sorted(evidence_index)),  # type: ignore[misc]
        sources=tuple(source_index[key] for key in sorted(source_index)),  # type: ignore[misc]
        findings=findings,
    )
