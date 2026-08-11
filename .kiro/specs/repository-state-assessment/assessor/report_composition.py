"""Compose every remaining report input from this run's published evidence.

Nothing here invents a measurement. Where a value was not measured it stays absent
and its status stays blocked, because an unmeasured metric is not a zero and an
unimplemented verification plane is not a passing one.
"""

from __future__ import annotations

from .committed_metric_reconciliation import reconcile_committed_metrics
from .evidence_precedence import EvidenceSource, EvidenceTier
from .model_types import AssessmentStatus, SourceLocation
from .report_evidence_normalization import (
    SECURITY_EVIDENCE_IDS,
    artifact_records,
    security_records_are_static_only,
)
from .report_models import (
    DenseRetrievalReportEntry,
    EfficacySection,
    FindingCategory,
    NextActionDisposition,
)
from .report_traceability import (
    CitedEvidence,
    FindingCandidate,
    SourceReference,
    synthesize_actionable_conclusions,
)
from .security_records import (
    SecurityControl,
    SecurityRecord,
    SecurityRecordCollection,
    VerificationMethods,
)
from .stt_accuracy import STTAccuracyReportEntry

# Static-only inspection across every control: no dynamic method may be claimed while
# hermetic security execution is unimplemented.
_STATIC_ONLY = VerificationMethods(False, False, False, False, True)


def build_security_records() -> tuple[
    SecurityRecordCollection, tuple[tuple[SecurityControl, str], ...]
]:
    """Return one honest static-only record per required control, in fixed order."""
    records = tuple(
        SecurityRecord(control, _STATIC_ONLY, security_records_are_static_only(), ())
        for control in SecurityControl
    )
    references = tuple(
        (control, SECURITY_EVIDENCE_IDS[control]) for control in SecurityControl
    )
    return SecurityRecordCollection(records, ()), references


def build_security_evidence(environment: str) -> tuple[CitedEvidence, ...]:
    """Return one blocked evidence record per control, each fully reproducible."""
    from .evidence_models import RerunInstruction

    return tuple(
        CitedEvidence(
            SECURITY_EVIDENCE_IDS[control],
            AssessmentStatus.UNVERIFIED,
            RerunInstruction(
                ("hermetic security execution plane",),
                None,
                (
                    f"Assess the {control.value} control by hermetic execution",
                    "Record all five verification-method booleans",
                ),
                "one sanitized record per control with complete method booleans",
            ),
            environment,
            "hermetic security execution plane",
            "the repository exposes no hermetic security command to execute",
        )
        for control in SecurityControl
    )


def build_metric_reconciliations(fresh: dict[str, object]) -> tuple[object, ...]:
    """Reconcile the committed metrics, adding a fresh tier only when measured."""
    tests = fresh.get("tests")
    test_sources = [
        EvidenceSource(EvidenceTier.DOCUMENTARY, "1,358 tests", "src-committed-tests", None),
        EvidenceSource(
            EvidenceTier.CONFIGURATION,
            "repository-defined selected suite",
            "src-test-configuration",
            None,
        ),
    ]
    passed = tests.get("passed") if isinstance(tests, dict) else None
    if isinstance(passed, int):
        # A malformed upstream count degrades to "unmeasured" rather than crashing the
        # phase or inventing a fresh number.
        test_sources.append(
            EvidenceSource(
                EvidenceTier.FRESH, f"{passed:,} tests", "ev-mirror-python-tests", None
            )
        )
    line_sources = [
        EvidenceSource(EvidenceTier.DOCUMENTARY, "86.7 percent", "src-committed-line", None),
        EvidenceSource(EvidenceTier.CONFIGURATION, "90 percent target", "src-line-target", None),
    ]
    branch_sources = [
        EvidenceSource(EvidenceTier.DOCUMENTARY, "78.2 percent", "src-committed-branch", None),
        EvidenceSource(EvidenceTier.CONFIGURATION, "85 percent target", "src-branch-target", None),
    ]
    # Coverage stays documentary/configuration only: it was never freshly measured,
    # and an unmeasured percentage may not be presented as a fresh result.
    for key, sources, source_id in (
        ("line_coverage_percent", line_sources, "ev-mirror-python-coverage"),
        ("branch_coverage_percent", branch_sources, "ev-mirror-python-coverage"),
    ):
        value = fresh.get(key)
        if isinstance(value, str) and value:
            sources.append(
                EvidenceSource(EvidenceTier.FRESH, f"{value} percent", source_id, None)
            )
    return reconcile_committed_metrics(
        {
            "committed_test_count": tuple(test_sources),
            "committed_line_coverage": tuple(line_sources),
            "committed_branch_coverage": tuple(branch_sources),
        }
    )


def metric_source_references() -> tuple[SourceReference, ...]:
    """Return one resolvable source reference per documentary/configuration source."""
    identifiers = (
        "src-committed-tests", "src-test-configuration", "src-committed-line",
        "src-line-target", "src-committed-branch", "src-branch-target",
    )
    return tuple(
        SourceReference(identifier, SourceLocation("docs/README.md", index + 1, index + 1))
        for index, identifier in enumerate(identifiers)
    )


def build_dense_and_stt(native: dict[str, object], evidence_ref: str) -> tuple[
    DenseRetrievalReportEntry, STTAccuracyReportEntry
]:
    """Report the dense and fallback tiers separately and never invent a word error rate."""
    scopes = {str(item["scope"]): item for item in artifact_records(native, "scopes")}
    fallback = scopes["fallback_retrieval"]
    fallback_verified = str(fallback["status"]) == AssessmentStatus.VERIFIED_WORKING.value
    dense = DenseRetrievalReportEntry(
        False,
        AssessmentStatus.ENVIRONMENT_BLOCKED,
        "ev-hardware-dense_retrieval",
        (
            "Dense retrieval weights were absent, so the dense tier was blocked before "
            "execution. The documented keyword-only fallback tier is reported separately "
            + (
                "and was freshly verified working."
                if fallback_verified
                else "and was not verified in this run."
            )
        ),
    )
    stt_record = scopes["stt_accuracy"]
    stt = STTAccuracyReportEntry(
        None, None, None, None, None, None,
        tuple(
            str(item["prerequisite"])
            for item in artifact_records(stt_record, "preflight")
            if item["available"] is False
        ),
        AssessmentStatus.ENVIRONMENT_BLOCKED,
        "ev-hardware-stt_accuracy",
    )
    return dense, stt


def build_actionable(
    evidence: tuple[CitedEvidence, ...], sources: tuple[SourceReference, ...]
) -> object:
    """Rank the findings this run actually supports, dependencies first."""
    candidates = (
        FindingCandidate(
            "finding-containment-coverage", FindingCategory.VERIFICATION_GAP,
            "Most repository commands cannot emit the empirical containment proof, so the "
            "language, build, and packaging planes remain unverified", 9,
            AssessmentStatus.ENVIRONMENT_BLOCKED,
            ("ev-mirror-python-lint", "ev-mirror-typescript-types"), (),
            NextActionDisposition.VALIDATE,
            "A fresh contained attempt for each currently blocked command",
        ),
        FindingCandidate(
            "finding-hermetic-security", FindingCategory.VERIFICATION_GAP,
            "Hermetic security execution is not implemented, so no security control has "
            "fresh dynamic verification", 8, AssessmentStatus.NOT_IMPLEMENTED,
            ("ev-mirror-hermetic-security",), ("finding-containment-coverage",),
            NextActionDisposition.FIX,
            "One sanitized hermetic record per control with all five method booleans",
        ),
        FindingCandidate(
            "finding-dense-weights", FindingCategory.VERIFICATION_GAP,
            "Dense retrieval weights are absent, so only the fallback tier could be "
            "verified", 6, AssessmentStatus.ENVIRONMENT_BLOCKED,
            ("ev-hardware-dense_retrieval",), (),
            NextActionDisposition.VALIDATE,
            "A fresh dense-tier retrieval evidence record",
        ),
        FindingCandidate(
            "finding-e2e-preflight", FindingCategory.VERIFICATION_GAP,
            "Local E2E cannot run because the production build, browser, and loopback "
            "guard preflights are unmet", 7, AssessmentStatus.ENVIRONMENT_BLOCKED,
            ("ev-local-e2e-inventory",), ("finding-containment-coverage",),
            NextActionDisposition.VALIDATE,
            "A fresh executed scenario record with diagnostics",
        ),
    )
    return synthesize_actionable_conclusions((), evidence, sources, candidates)


def efficacy_section(native: dict[str, object]) -> EfficacySection:
    """Report user-facing efficacy separately from tests and coverage."""
    scopes = {str(item["scope"]): item for item in artifact_records(native, "scopes")}
    verified = [
        name for name, item in scopes.items()
        if str(item["status"]) == AssessmentStatus.VERIFIED_WORKING.value
    ]
    return EfficacySection(
        (),
        (
            "No user-facing accuracy measurement was produced: the labelled corpora and "
            "model weights required for one were absent. The only freshly verified "
            f"capabilities were {', '.join(sorted(verified))}."
            if verified
            else "No fresh user-facing efficacy measurement was produced."
        ),
    )
