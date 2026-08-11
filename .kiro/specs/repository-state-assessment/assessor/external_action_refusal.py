"""Pure fail-closed model for hermetic external-action refusal probes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RefusalCondition(StrEnum):
    """Permitted dynamic refusal conditions; neither can reach a provider."""

    ABSENT_CREDENTIALS = "absent_credentials"
    REJECTING_LOOPBACK_FAKE = "rejecting_loopback_fake"


class PendingActionState(StrEnum):
    """States relevant to proving that refusal never executes an action."""

    PENDING = "pending"
    EXECUTED = "executed"


@dataclass(frozen=True, slots=True)
class ExternalActionRequest:
    action_id: str
    action_kind: str
    synthetic_payload: str


@dataclass(frozen=True, slots=True)
class UserDataHash:
    path_label: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ExternalActionRefusal:
    request: ExternalActionRequest
    condition: RefusalCondition
    failure_indication: str
    state_before: PendingActionState
    state_after: PendingActionState
    non_loopback_request_count: int
    provider_side_effect_count: int
    loopback_fake_request_count: int
    data_hashes_before: tuple[UserDataHash, ...]
    data_hashes_after: tuple[UserDataHash, ...]


def refuse_external_action(request: ExternalActionRequest, condition: RefusalCondition, preexisting_hashes: tuple[UserDataHash, ...]) -> ExternalActionRefusal:
    """Return the only safe outcome for an action exercised under refusal."""
    if not isinstance(condition, RefusalCondition):  # fail-closed: unrecognised condition cannot yield a refusal result
        raise TypeError("condition must be a RefusalCondition")
    outcomes = {  # exhaustive mapping: every supported condition owns its message and counters
        RefusalCondition.ABSENT_CREDENTIALS: ("credentials absent", 0, 0, 0),
        RefusalCondition.REJECTING_LOOPBACK_FAKE: (
            "loopback fake rejected operation",
            0,
            0,
            1,
        ),
    }
    if condition not in outcomes:  # fail-closed: future conditions require an explicit refusal outcome
        raise ValueError("condition has no refusal outcome")
    failure, non_loopback_count, side_effect_count, loopback_count = outcomes[condition]
    return ExternalActionRefusal(
        request,
        condition,
        failure,
        PendingActionState.PENDING,
        PendingActionState.PENDING,
        non_loopback_count,
        side_effect_count,
        loopback_count,
        preexisting_hashes,
        preexisting_hashes,
    )
