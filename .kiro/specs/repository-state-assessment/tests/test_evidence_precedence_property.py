"""Property 2: evidence precedence and conflicts are deterministic.

Feature: repository-state-assessment, Property 2: Evidence precedence and conflicts are deterministic
Validates: Requirements 1.2, 1.3, 2.5, 2.6, 2.7, 7.6
"""

from datetime import date, timedelta

from assessor import EvidenceSource, EvidenceTier, select_evidence

_TIER_ORDER = tuple(EvidenceTier)
_CASES = 512
_ALL_MASKS = set(range(1 << len(_TIER_ORDER)))


def _case_evidence(case_number: int) -> tuple[EvidenceSource, ...]:
    availability_mask = case_number % 32
    phase = case_number // 32
    date_mode = phase % 3
    sources: list[EvidenceSource] = []
    for index, tier in enumerate(_TIER_ORDER):
        if not availability_mask & (1 << index):
            continue
        value = "shared" if phase % 4 == 0 else f"value-{index % 2}"
        if date_mode == 0:
            collected_on = None
        elif date_mode == 1:
            collected_on = date(2026, 1, 1) + timedelta(days=index)
        else:
            collected_on = None if index % 2 == 0 else date(2026, 2, index + 1)
        sources.append(EvidenceSource(tier, value, f"source-{index}", collected_on))
    # Deliberately vary input order: selection and record ordering must not depend on it.
    return tuple(reversed(sources)) if phase % 2 else tuple(sources)


def test_property_2_evidence_precedence_and_conflicts_are_deterministic() -> None:
    seen_masks: set[int] = set()
    conflict_date_modes: set[str] = set()
    selected_tiers: set[EvidenceTier] = set()

    for case_number in range(_CASES):
        evidence = _case_evidence(case_number)
        seen_masks.add(case_number % 32)
        decision = select_evidence(evidence)
        applicable = sorted(evidence, key=lambda item: _TIER_ORDER.index(item.tier))

        if not applicable:
            assert decision.selected is None
            assert decision.conflict is None
            continue

        expected = applicable[0]
        selected_tiers.add(expected.tier)
        assert decision.selected == expected
        assert decision.selected_conclusion == expected.value
        assert decision.precedence_basis == (
            f"{expected.tier.value} is the highest available applicable evidence tier"
        )
        conflicting = len({item.value for item in applicable}) > 1
        if not conflicting:
            assert decision.conflict is None
            continue

        assert decision.conflict is not None
        assert decision.conflict.evidence == tuple(applicable)
        assert decision.conflict.selected_conclusion == expected.value
        assert decision.conflict.precedence_basis == decision.precedence_basis
        assert {
            (item.value, item.source, item.collected_on) for item in decision.conflict.evidence
        } == {(item.value, item.source, item.collected_on) for item in evidence}

        known = [item.collected_on is not None for item in decision.conflict.evidence]
        if all(known):
            conflict_date_modes.add("all-known")
        elif any(known):
            conflict_date_modes.add("mixed")
        else:
            conflict_date_modes.add("all-unknown")

        assert select_evidence(reversed(evidence)) == decision

    assert seen_masks == _ALL_MASKS
    assert selected_tiers == set(_TIER_ORDER)
    assert conflict_date_modes == {"all-known", "all-unknown", "mixed"}


def test_evidence_precedence_examples_cover_fresh_and_historical_only() -> None:
    historical = EvidenceSource(EvidenceTier.HISTORICAL, "old", "prior.json", None)
    fresh = EvidenceSource(EvidenceTier.FRESH, "current", "fresh-run", date(2026, 3, 1))

    historical_decision = select_evidence((historical,))
    assert historical_decision.selected == historical
    assert historical_decision.selected_tier is EvidenceTier.HISTORICAL

    fresh_decision = select_evidence((historical, fresh))
    assert fresh_decision.selected == fresh
    assert fresh_decision.conflict is not None
    assert fresh_decision.conflict.evidence == (fresh, historical)
