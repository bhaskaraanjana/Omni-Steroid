"""Property 9: cleanup affects only assessment-owned processes.

**Validates: Requirements 4.7, 4.8, 5.8**
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from assessor.model_types import OwnedProcess, ProcessOwnership, ZonedTimestamp
from assessor.process_cleanup import (
    CleanupMode,
    ProcessSnapshot,
    select_cleanup_processes,
)

_SEED = 20260708
_CASES = 256


def _identity(case: int, index: int, pid: int, parent_pid: int | None) -> OwnedProcess:
    return OwnedProcess(
        pid=pid,
        created_at=ZonedTimestamp(
            datetime(2026, 7, 8, tzinfo=timezone.utc)
            + timedelta(seconds=case * 100 + index)
        ),
        executable=f"C:\\assessment tools\\worker-{index % 4}.exe",
        parent_pid=parent_pid,
    )


def _owned_forest(rng: random.Random, case: int) -> tuple[OwnedProcess, ...]:
    base_pid = 10_000 + case * 100
    processes: list[OwnedProcess] = []
    for index in range(rng.randint(6, 12)):
        parent_pid = None if index == 0 else rng.choice(processes).pid
        processes.append(_identity(case, index, base_pid + index, parent_pid))
    return tuple(processes)


def _reused(identity: OwnedProcess, case: int) -> OwnedProcess:
    return OwnedProcess(
        pid=identity.pid,
        created_at=ZonedTimestamp(
            identity.created_at.value + timedelta(microseconds=case + 1)
        ),
        executable=identity.executable,
        parent_pid=identity.parent_pid,
    )


def _pre_existing_forest(
    rng: random.Random, case: int
) -> tuple[ProcessSnapshot, ...]:
    base_pid = 1_000_000 + case * 100
    identities: list[OwnedProcess] = []
    snapshots: list[ProcessSnapshot] = []
    for index in range(rng.randint(2, 8)):
        parent_pid = None if index == 0 else rng.choice(identities).pid
        identity = _identity(case + 50_000, index, base_pid + index, parent_pid)
        identities.append(identity)
        snapshots.append(
            ProcessSnapshot(
                identity=identity,
                ownership_token=None if index % 2 == 0 else f"other-run-{case}",
            )
        )
    return tuple(snapshots)


def test_pid_reuse_and_foreign_tokens_are_preserved() -> None:
    owned = _identity(1, 0, 42, None)
    ownership = ProcessOwnership("assessment-1", "snapshot", (owned,))
    reused = ProcessSnapshot(_reused(owned, 1), "assessment-1")
    foreign = ProcessSnapshot(owned, "another-assessment")
    matching = ProcessSnapshot(owned, "assessment-1")

    result = select_cleanup_processes(
        ownership, (reused, foreign, matching), CleanupMode.TIMEOUT
    )

    assert result.terminate == (matching,)
    assert result.preserve == (reused, foreign)


def test_property_9_cleanup_affects_only_assessment_owned_processes() -> None:
    """Generate owned/pre-existing forests across every termination mode.

    **Validates: Requirements 4.7, 4.8, 5.8**
    """
    rng = random.Random(_SEED)
    seen_modes: set[CleanupMode] = set()

    for case in range(_CASES):
        token = f"assessment-{case}"
        owned = _owned_forest(rng, case)
        ownership = ProcessOwnership(token, "snapshot", owned)
        observed: list[ProcessSnapshot] = list(_pre_existing_forest(rng, case))
        expected_terminated: set[ProcessSnapshot] = set()
        reused_snapshots: set[ProcessSnapshot] = set()

        for index, identity in enumerate(owned):
            disposition = (index + case) % 3
            if disposition == 0:
                snapshot = ProcessSnapshot(identity, token)
                observed.append(snapshot)
                expected_terminated.add(snapshot)
            elif disposition == 1:
                snapshot = ProcessSnapshot(_reused(identity, case), token)
                observed.append(snapshot)
                reused_snapshots.add(snapshot)
            # disposition 2 represents an owned process that already exited.

        rng.shuffle(observed)
        mode = tuple(CleanupMode)[case % len(CleanupMode)]
        result = select_cleanup_processes(ownership, tuple(observed), mode)
        seen_modes.add(result.mode)

        observed_set = set(observed)
        terminated_set = set(result.terminate)
        preserved_set = set(result.preserve)
        expected_preserved = observed_set - expected_terminated

        assert terminated_set == expected_terminated
        assert preserved_set == expected_preserved
        assert terminated_set.isdisjoint(preserved_set)
        assert terminated_set | preserved_set == observed_set
        assert reused_snapshots <= preserved_set
        assert all(
            snapshot.ownership_token == token
            and snapshot.identity in ownership.processes
            for snapshot in result.terminate
        )
        assert all(
            snapshot.ownership_token != token
            or snapshot.identity not in ownership.processes
            for snapshot in result.preserve
        )

    assert seen_modes == set(CleanupMode)
