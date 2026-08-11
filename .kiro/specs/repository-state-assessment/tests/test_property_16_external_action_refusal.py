"""Property 16: Refused external actions preserve state.

**Validates: Requirements 7.8, 7.9, 7.10**
"""

from __future__ import annotations

import random
from hashlib import sha256

from assessor.external_action_refusal import (
    ExternalActionRequest,
    PendingActionState,
    RefusalCondition,
    UserDataHash,
    refuse_external_action,
)

_SEED = 20260708
_CASES = 256
_ACTION_KINDS = ("calendar_event", "contact_upsert", "vault_write", "gmail_draft")


def _hashes(rng: random.Random, case: int) -> tuple[UserDataHash, ...]:
    return tuple(
        UserDataHash(
            f"[USER_DATA_{case}_{index}]",
            sha256(rng.randbytes(rng.randint(0, 96))).hexdigest(),
        )
        for index in range(rng.randint(0, 8))
    )


def test_absent_credentials_fail_without_any_network_request() -> None:
    request = ExternalActionRequest("action-1", "calendar_event", "synthetic")
    hashes = (UserDataHash("[USER_DATA]", sha256(b"before").hexdigest()),)

    result = refuse_external_action(request, RefusalCondition.ABSENT_CREDENTIALS, hashes)

    assert result.failure_indication == "credentials absent"
    assert result.loopback_fake_request_count == 0
    assert result.data_hashes_after == hashes


def test_rejecting_fake_is_loopback_only_and_does_not_execute() -> None:
    request = ExternalActionRequest("action-2", "gmail_draft", "synthetic")
    result = refuse_external_action(request, RefusalCondition.REJECTING_LOOPBACK_FAKE, ())

    assert result.failure_indication == "loopback fake rejected operation"
    assert result.loopback_fake_request_count == 1
    assert result.state_after is PendingActionState.PENDING


def test_property_16_refused_external_actions_preserve_state() -> None:
    """Generate 256 synthetic requests across both refusal conditions.

    **Validates: Requirements 7.8, 7.9, 7.10**
    """
    rng = random.Random(_SEED)
    seen_conditions: set[RefusalCondition] = set()

    for case in range(_CASES):
        condition = tuple(RefusalCondition)[case % len(RefusalCondition)]
        request = ExternalActionRequest(
            action_id=f"synthetic-action-{case}",
            action_kind=_ACTION_KINDS[case % len(_ACTION_KINDS)],
            synthetic_payload="".join(
                rng.choice("abcXYZ09 ä日本語") for _ in range(rng.randint(0, 80))
            ),
        )
        before = _hashes(rng, case)
        result = refuse_external_action(request, condition, before)
        seen_conditions.add(result.condition)

        assert result.request == request
        assert result.failure_indication
        assert result.non_loopback_request_count == 0
        assert result.provider_side_effect_count == 0
        assert result.state_before is PendingActionState.PENDING
        assert result.state_after is PendingActionState.PENDING
        assert result.state_after is not PendingActionState.EXECUTED
        assert result.data_hashes_before == before
        assert result.data_hashes_after == before
        assert tuple(item.path_label for item in result.data_hashes_after) == tuple(
            item.path_label for item in before
        )

    assert _CASES >= 100
    assert seen_conditions == set(RefusalCondition)
