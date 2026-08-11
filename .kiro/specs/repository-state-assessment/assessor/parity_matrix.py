"""Pure construction of the canonical competitor parity-matrix shape."""

from __future__ import annotations

from collections.abc import Iterable

from .model_types import AssessmentStatus
from .report_models import BenchmarkSet, ParityRow

GRANOLA_CAPABILITIES = (
    "bot-free meeting capture",
    "live transcription",
    "user-authored notes",
    "enhanced notes",
    "live assistance",
    "meeting library",
    "meeting search",
    "meeting chat",
    "calendar integration",
    "auto-detection",
    "export",
    "privacy",
    "platform support",
)

WISPR_FLOW_CAPABILITIES = (
    "global activation",
    "push-to-talk",
    "locked recording",
    "speech transcription",
    "cross-application text injection",
    "cleanup styles",
    "personal dictionary",
    "raw-text retention",
    "faithfulness protection",
    "dictation history",
    "history search",
    "note mode",
    "command mode",
    "latency",
    "accuracy",
    "platform support",
)

_CANONICAL_CAPABILITIES = {
    BenchmarkSet.GRANOLA: GRANOLA_CAPABILITIES,
    BenchmarkSet.WISPR_FLOW: WISPR_FLOW_CAPABILITIES,
}

def _default_row(benchmark_set: BenchmarkSet, capability: str) -> ParityRow:
    """Create an explicit unverified row before later evidence joins."""
    slug = capability.replace(" ", "-")
    return ParityRow(
        row_id=f"{benchmark_set.value}-{slug}",
        benchmark_set=benchmark_set,
        benchmark_capability=capability,
        benchmark_source=None,
        benchmark_source_date=None,
        benchmark_basis_status=AssessmentStatus.UNVERIFIED,
        omni_documentary_claim_refs=(),
        implementation_locations=(),
        fresh_evidence_refs=(),
        primary_status=AssessmentStatus.UNVERIFIED,
        limitation="No evidence joined",
        parity_conclusion="Unverified",
        measurements=(),
    )


def build_canonical_parity_matrix(
    evidence_rows: Iterable[ParityRow] = (),
) -> tuple[ParityRow, ...]:
    """Return every canonical row once, independent of evidence input order."""
    joined: dict[tuple[BenchmarkSet, str], ParityRow] = {}
    for row in evidence_rows:
        capabilities = _CANONICAL_CAPABILITIES.get(row.benchmark_set, ())
        if row.benchmark_capability not in capabilities:
            raise ValueError("evidence row is not a canonical benchmark capability")
        joined[(row.benchmark_set, row.benchmark_capability)] = row

    return tuple(
        joined.get(
            (benchmark_set, capability),
            _default_row(benchmark_set, capability),
        )
        for benchmark_set, capabilities in _CANONICAL_CAPABILITIES.items()
        for capability in capabilities
    )


# Re-exported so `parity_matrix` remains the single import surface for parity work.
from .parity_benchmark_source_selection import (  # noqa: E402
    BenchmarkSource as BenchmarkSource,
)
from .parity_benchmark_source_selection import (  # noqa: E402
    BenchmarkSourceDecision as BenchmarkSourceDecision,
)
from .parity_benchmark_source_selection import (  # noqa: E402
    apply_benchmark_source_decision as apply_benchmark_source_decision,
)
from .parity_benchmark_source_selection import (  # noqa: E402
    select_benchmark_source as select_benchmark_source,
)
from .parity_evidence_conclusions import (  # noqa: E402
    ParityBehaviorEvidence as ParityBehaviorEvidence,
)
from .parity_evidence_conclusions import (  # noqa: E402
    ParityConclusionDecision as ParityConclusionDecision,
)
from .parity_evidence_conclusions import (  # noqa: E402
    derive_evidence_parity as derive_evidence_parity,
)
