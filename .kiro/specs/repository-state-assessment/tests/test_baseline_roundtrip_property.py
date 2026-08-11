"""Property 1 coverage for complete, lossless baseline JSON round trips."""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

from assessor import (
    AssessmentBaseline,
    HardwareInventory,
    OperatingSystemInventory,
    RepositoryHead,
    RepositoryHeadKind,
    ToolVersion,
    WorkspaceChange,
    ZonedTimestamp,
)

_SEED = 20260708
_CASES = 128
_UNICODE_PATH_PARTS = (
    "src/naïve résumé.py",
    "資料/会議メモ.txt",
    "данные/изменение.json",
    "emoji/rocket-🚀.md",
    "العربية/ملف.toml",
)


def _path(rng: random.Random, case_index: int, item_index: int) -> str:
    stem = rng.choice(_UNICODE_PATH_PARTS)
    return f"case-{case_index}/{item_index}-{stem}"


def _changes(
    rng: random.Random, case_index: int, *, empty_every: int
) -> tuple[WorkspaceChange, ...]:
    count = 0 if case_index % empty_every == 0 else rng.randint(1, 4)
    changes: list[WorkspaceChange] = []
    for item_index in range(count):
        renamed = (case_index + item_index) % 3 == 0
        changes.append(
            WorkspaceChange(
                path=_path(rng, case_index, item_index),
                status_code="R." if renamed else rng.choice(("M.", ".M", "A.")),
                original_path=(
                    _path(rng, case_index, item_index + 100) if renamed else None
                ),
            )
        )
    return tuple(changes)


def _hardware(rng: random.Random, case_index: int) -> tuple[HardwareInventory, ...]:
    count = 0 if case_index % 4 == 0 else rng.randint(1, 3)
    return tuple(
        HardwareInventory(
            category=rng.choice(("cpu", "gpu", "audio", "memory")),
            name=f"装置-{case_index}-{item_index}-Éclair",
            attributes=(
                ("driver", f"v{rng.randint(0, 99)}.{rng.randint(0, 99)}"),
                ("endpoint", _path(rng, case_index, item_index)),
            )
            if (case_index + item_index) % 2
            else (),
        )
        for item_index in range(count)
    )


def _tools(rng: random.Random, case_index: int) -> tuple[ToolVersion, ...]:
    count = 0 if case_index % 5 == 0 else rng.randint(1, 4)
    return tuple(
        ToolVersion(
            name=rng.choice(("Python", "Node.js", "Cargo", "Vitest")),
            version=f"{rng.randint(0, 30)}.{rng.randint(0, 20)}.{rng.randint(0, 99)}",
            executable=f"C:\\工具\\case {case_index}\\tool-{item_index}.exe",
        )
        for item_index in range(count)
    )


def _baseline(rng: random.Random, case_index: int) -> AssessmentBaseline:
    kind = RepositoryHeadKind.BRANCH if case_index % 2 == 0 else RepositoryHeadKind.DETACHED
    offset_minutes = rng.choice((-720, -330, -60, 0, 345, 570, 840))
    started_at = datetime(
        2020 + rng.randint(0, 10),
        rng.randint(1, 12),
        rng.randint(1, 28),
        rng.randint(0, 23),
        rng.randint(0, 59),
        rng.randint(0, 59),
        rng.randint(0, 999999),
        tzinfo=timezone(timedelta(minutes=offset_minutes)),
    )
    untracked_count = 0 if case_index % 6 == 0 else rng.randint(1, 4)

    return AssessmentBaseline(
        run_id=f"run-{case_index:03d}-測試",
        repository_root=f"C:\\DEV\\Omni Steroid\\répo-{case_index}",
        head=RepositoryHead(
            commit=f"{case_index:040x}",
            kind=kind,
            branch_name=f"feature/基線-{case_index}" if kind is RepositoryHeadKind.BRANCH else None,
        ),
        started_at=ZonedTimestamp(started_at),
        staged_changes=_changes(rng, case_index, empty_every=2),
        unstaged_changes=_changes(rng, case_index, empty_every=3),
        untracked_paths=tuple(
            _path(rng, case_index, item_index + 200)
            for item_index in range(untracked_count)
        ),
        operating_system=OperatingSystemInventory(
            name=rng.choice(("Windows", "Linux", "macOS")),
            version=f"版本-{rng.randint(1, 20)}.{rng.randint(0, 9)}",
            build=None if case_index % 3 == 0 else str(rng.randint(1000, 99999)),
        ),
        hardware=_hardware(rng, case_index),
        tools=_tools(rng, case_index),
        source_manifest_ref=f"manifests/source-{case_index}-源.json",
        designated_roots=(
            f"C:\\Temp\\assessment {case_index}",
            f".kiro/specs/評估/output-{case_index}",
        ),
        mirror_manifest_ref=(
            None if case_index % 4 == 0 else f"manifests/mirror-{case_index}-鏡.json"
        ),
    )


def test_complete_baseline_records_round_trip_losslessly() -> None:
    """Property 1: baseline records are complete and lossless.

    **Validates: Requirements 1.1**
    """
    rng = random.Random(_SEED)

    for case_index in range(_CASES):
        baseline = _baseline(rng, case_index)
        serialized = baseline.to_dict()
        json_document = json.dumps(serialized, ensure_ascii=False, sort_keys=True)
        decoded = json.loads(json_document)
        restored = AssessmentBaseline.from_dict(decoded)

        assert decoded == serialized
        assert restored == baseline, f"baseline round trip failed for case {case_index}"
