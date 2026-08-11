"""Property 18: Report conclusions are traceable and actionable.

**Validates: Requirements 9.8, 9.9, 9.10, 9.12, 9.13**
"""

# ruff: noqa: S101, S311

from __future__ import annotations

import random

import pytest

from assessor.evidence_models import RerunInstruction
from assessor.model_types import AssessmentStatus, ExactArgumentVector, SourceLocation
from assessor.report_models import FindingCategory, NextActionDisposition
from assessor.report_traceability import (
    CitedEvidence,
    FindingCandidate,
    ReportConclusion,
    SourceReference,
    synthesize_actionable_conclusions,
)

_SEED = 20260708
_CASES = 128
_FRESH_STATUSES = (
    AssessmentStatus.VERIFIED_WORKING,
    AssessmentStatus.VERIFIED_PARTIAL,
    AssessmentStatus.FRESH_FAILURE,
    AssessmentStatus.INTEGRATION_FAILED,
)


def _rerun(case: int, blocked: bool, procedure: bool) -> RerunInstruction:
    prerequisite = f"prerequisite-{case}"
    return RerunInstruction(
        prerequisites=(prerequisite,) if blocked else ("python",),
        exact_argv=None if procedure else ExactArgumentVector(("python", "-m", f"check_{case}")),
        numbered_procedure=(
            (f"Make {prerequisite} available", f"Run check {case}")
            if procedure
            else None
        ),
        expected_observable=f"observable result {case}",
    )


def _effective_priorities(candidates: tuple[FindingCandidate, ...]) -> dict[str, int]:
    priorities = {candidate.finding_id: candidate.impact_priority for candidate in candidates}
    changed = True
    while changed:
        changed = False
        for candidate in candidates:
            for dependency_id in candidate.dependency_ids:
                if priorities[candidate.finding_id] > priorities[dependency_id]:
                    priorities[dependency_id] = priorities[candidate.finding_id]
                    changed = True
    return priorities


def _generated_graph(rng: random.Random, case: int):
    evidence = []
    for index in range(rng.randint(1, 8)):
        blocked = index % 5 == 0
        prerequisite = f"prerequisite-{case}-{index}"
        rerun = RerunInstruction(
            prerequisites=(prerequisite,) if blocked else ("python",),
            exact_argv=(
                None
                if index % 2
                else ExactArgumentVector(("python", "-m", f"check_{case}_{index}"))
            ),
            numbered_procedure=(
                (f"Prepare check {case}-{index}", f"Run check {case}-{index}")
                if index % 2
                else None
            ),
            expected_observable=f"observable result {case}-{index}",
        )
        evidence.append(
            CitedEvidence(
                evidence_id=f"evidence-{case}-{index}",
                primary_status=(
                    AssessmentStatus.ENVIRONMENT_BLOCKED
                    if blocked
                    else _FRESH_STATUSES[index % len(_FRESH_STATUSES)]
                ),
                rerun=rerun,
                assessment_environment=f"Windows fixture {case}",
                unavailable_prerequisite=prerequisite if blocked else None,
                detection_evidence=f"probe-{case}-{index}" if blocked else None,
            )
        )

    sources = tuple(
        SourceReference(
            source_id=f"source-{case}-{index}",
            location=SourceLocation(f"docs/generated-{case}.md", index + 1, index + 1),
        )
        for index in range(rng.randint(1, 8))
    )
    conclusions = []
    for index in range(rng.randint(1, 12)):
        evidence_refs = tuple(
            item.evidence_id for item in rng.sample(evidence, rng.randint(0, len(evidence)))
        )
        source_refs = tuple(
            item.source_id for item in rng.sample(sources, rng.randint(0, len(sources)))
        )
        if not evidence_refs and not source_refs:
            evidence_refs = (evidence[index % len(evidence)].evidence_id,)
        conclusions.append(
            ReportConclusion(
                conclusion_id=f"conclusion-{case}-{index}",
                text=f"generated conclusion {case}-{index}",
                evidence_refs=evidence_refs,
                source_refs=source_refs,
            )
        )

    findings = []
    finding_count = rng.randint(1, 10)
    for index in range(finding_count):
        dependency_pool = [item.finding_id for item in findings]
        dependencies = tuple(
            sorted(rng.sample(dependency_pool, rng.randint(0, min(2, len(dependency_pool)))))
        )
        findings.append(
            FindingCandidate(
                finding_id=f"finding-{case}-{index}",
                category=tuple(FindingCategory)[index % len(FindingCategory)],
                impact=f"impact {case}-{index}",
                impact_priority=rng.randint(1, 5),
                primary_status=tuple(AssessmentStatus)[index % len(AssessmentStatus)],
                evidence_refs=(evidence[index % len(evidence)].evidence_id,),
                dependency_ids=dependencies,
                disposition=tuple(NextActionDisposition)[index % len(NextActionDisposition)],
                completion_evidence_required=f"completion evidence {case}-{index}",
            )
        )
    return tuple(conclusions), tuple(evidence), sources, tuple(findings)


def test_unresolvable_conclusion_and_incomplete_blocked_rerun_are_rejected() -> None:
    source = SourceReference("source-1", SourceLocation("README.md", 1, 1))
    conclusion = ReportConclusion("conclusion-1", "claim", (), ("missing-source",))

    with pytest.raises(ValueError, match="unknown source"):
        synthesize_actionable_conclusions((conclusion,), (), (source,), ())

    blocked = CitedEvidence(
        "evidence-1",
        AssessmentStatus.ENVIRONMENT_BLOCKED,
        _rerun(1, blocked=True, procedure=True),
        "Windows fixture",
        "prerequisite-1",
        None,
    )
    with pytest.raises(ValueError, match="detection evidence"):
        synthesize_actionable_conclusions((), (blocked,), (), ())


def test_property_18_report_conclusions_are_traceable_and_actionable() -> None:
    """Generate 128 evidence/source graphs and finding dependency graphs.

    **Validates: Requirements 9.8, 9.9, 9.10, 9.12, 9.13**
    """
    rng = random.Random(_SEED)

    for case in range(_CASES):
        conclusions, evidence, sources, candidates = _generated_graph(rng, case)
        shuffled_conclusions = list(conclusions)
        shuffled_evidence = list(evidence)
        shuffled_sources = list(sources)
        shuffled_candidates = list(candidates)
        for values in (
            shuffled_conclusions,
            shuffled_evidence,
            shuffled_sources,
            shuffled_candidates,
        ):
            rng.shuffle(values)

        result = synthesize_actionable_conclusions(
            tuple(shuffled_conclusions),
            tuple(shuffled_evidence),
            tuple(shuffled_sources),
            tuple(shuffled_candidates),
        )
        evidence_ids = {item.evidence_id for item in result.evidence}
        source_ids = {item.source_id for item in result.sources}

        assert len(result.conclusions) == len(conclusions)
        for conclusion in result.conclusions:
            assert conclusion.evidence_refs or conclusion.source_refs
            assert set(conclusion.evidence_refs) <= evidence_ids
            assert set(conclusion.source_refs) <= source_ids

        for item in result.evidence:
            assert item.assessment_environment
            assert item.rerun.expected_observable
            assert (item.rerun.exact_argv is None) != (
                item.rerun.numbered_procedure is None
            )
            if item.rerun.numbered_procedure is not None:
                assert all(item.rerun.numbered_procedure)
            if item.primary_status is AssessmentStatus.ENVIRONMENT_BLOCKED:
                assert item.unavailable_prerequisite
                assert item.detection_evidence
                assert item.unavailable_prerequisite in item.rerun.prerequisites

        ranks = tuple(finding.rank for finding in result.findings)
        assert ranks == tuple(range(1, len(result.findings) + 1))
        assert len({finding.finding_id for finding in result.findings}) == len(
            result.findings
        )
        ranked_by_id = {finding.finding_id: finding for finding in result.findings}
        candidate_by_id = {candidate.finding_id: candidate for candidate in candidates}
        for finding in result.findings:
            candidate = candidate_by_id[finding.finding_id]
            assert isinstance(finding.disposition, NextActionDisposition)
            assert finding.disposition is candidate.disposition
            assert finding.completion_evidence_required
            assert set(finding.evidence_refs) <= evidence_ids
            assert all(
                ranked_by_id[dependency_id].rank < finding.rank
                for dependency_id in finding.dependency_ids
            )

        effective = _effective_priorities(candidates)
        emitted: set[str] = set()
        remaining = set(candidate_by_id)
        for finding in result.findings:
            ready = [
                finding_id
                for finding_id in remaining
                if set(candidate_by_id[finding_id].dependency_ids) <= emitted
            ]
            expected = min(ready, key=lambda item: (-effective[item], item))
            assert finding.finding_id == expected
            emitted.add(finding.finding_id)
            remaining.remove(finding.finding_id)

        repeated = synthesize_actionable_conclusions(
            tuple(reversed(conclusions)),
            tuple(reversed(evidence)),
            tuple(reversed(sources)),
            tuple(reversed(candidates)),
        )
        assert repeated.findings == result.findings

    assert _CASES >= 100
