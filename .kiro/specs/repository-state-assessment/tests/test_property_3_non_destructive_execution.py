"""Property 3: assessment execution preserves every pre-existing source byte.

**Validates: Requirements 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 3.17, 9.14**
"""

from __future__ import annotations

import random
import string
from hashlib import sha256

from assessor import AssessmentStatus
from assessor.preservation import (
    AssessmentTermination,
    PlannedOperation,
    PlannedWrite,
    WorkspaceFile,
    evaluate_non_destructive_execution,
    is_under_designated_root,
)

_SEED = 20260708
_CASES = 256


def _bytes(rng: random.Random) -> bytes:
    alphabet = string.ascii_letters + string.digits + " äöü日本語"
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 80))).encode(
        "utf-8"
    )


def _fixture_tree(rng: random.Random, case: int) -> tuple[WorkspaceFile, ...]:
    tracked = tuple(
        WorkspaceFile(f"src/{case}/tracked-{index}.py", _bytes(rng), True)
        for index in range(rng.randint(1, 4))
    )
    untracked = tuple(
        WorkspaceFile(f"notes/{case}/untracked-{index}.txt", _bytes(rng), False)
        for index in range(rng.randint(1, 4))
    )
    return tracked + untracked


def _operation(
    case: int,
    index: int,
    admitted: bool,
    path: str,
    content: bytes,
) -> PlannedOperation:
    return PlannedOperation(
        operation_id=f"case-{case}-operation-{index}",
        command_or_procedure=("fixture-write", path),
        requested_admission=admitted,
        writes=(PlannedWrite(path, content),),
        dependent_check_ids=(f"check-{case}-{index}",),
    )


def _operations(
    rng: random.Random,
    case: int,
    source: tuple[WorkspaceFile, ...],
    roots: tuple[str, ...],
) -> tuple[PlannedOperation, ...]:
    operations = [
        _operation(case, 0, True, f"{roots[0]}/safe-{case}.bin", _bytes(rng)),
        _operation(case, 1, True, rng.choice(source).path, _bytes(rng)),
        _operation(case, 2, False, f"{roots[1]}/rejected-{case}.json", _bytes(rng)),
        _operation(case, 3, True, f"outside/{case}/escaped.log", _bytes(rng)),
    ]
    for index in range(4, rng.randint(5, 10)):
        disposition = rng.choice(("safe", "source", "outside", "rejected"))
        if disposition == "safe":
            path = f"{rng.choice(roots)}/generated-{case}-{index}.dat"
            admitted = True
        elif disposition == "source":
            path = rng.choice(source).path
            admitted = True
        elif disposition == "outside":
            path = f"workspace/{case}/generated-{index}.dat"
            admitted = True
        else:
            path = f"{roots[0]}/denied-{case}-{index}.dat"
            admitted = False
        operations.append(_operation(case, index, admitted, path, _bytes(rng)))
    return tuple(operations)


def _hashes(files: tuple[WorkspaceFile, ...]) -> dict[str, str]:
    return {item.path: sha256(item.content).hexdigest() for item in files}


def test_unsafe_write_has_complete_omission_evidence() -> None:
    source = (WorkspaceFile("src/app.py", b"original", True),)
    operation = _operation(0, 0, True, "src/app.py", b"replacement")

    result = evaluate_non_destructive_execution(
        source,
        (operation,),
        ("run/temp", "spec/assessment-output/run"),
        AssessmentTermination.FAILURE,
    )

    assert result.source_after == source
    assert result.observed_writes == ()
    assert result.omissions[0].command_or_procedure == operation.command_or_procedure
    assert result.omissions[0].affected_content[0].path == "src/app.py"
    assert result.omissions[0].affected_content[0].sha256 == sha256(b"replacement").hexdigest()
    assert result.omissions[0].dependent_checks[0].status is AssessmentStatus.UNVERIFIED
    assert result.final_comparison.preservation_confirmed


def test_property_assessment_execution_is_non_destructive() -> None:
    """Generate source trees and operations across every terminal outcome."""
    rng = random.Random(_SEED)
    seen_terminations: set[AssessmentTermination] = set()

    for case in range(_CASES):
        source = _fixture_tree(rng, case)
        roots = (f"runs/{case}/temp", f"spec/assessment-output/{case}")
        operations = _operations(rng, case, source, roots)
        termination = tuple(AssessmentTermination)[case % len(AssessmentTermination)]

        result = evaluate_non_destructive_execution(
            source, operations, roots, termination
        )
        seen_terminations.add(result.termination)

        assert {item.path for item in result.source_after} == {
            item.path for item in source
        }
        assert _hashes(result.source_after) == _hashes(source)
        assert {item.path for item in result.source_after if item.tracked} == {
            item.path for item in source if item.tracked
        }
        assert {item.path for item in result.source_after if not item.tracked} == {
            item.path for item in source if not item.tracked
        }

        assert result.observed_writes
        assert all(is_under_designated_root(path, roots) for path in result.observed_writes)
        assert set(result.observed_writes) == {
            path for path, _content in result.artifact_bytes
        }

        source_paths = {item.path for item in source}
        expected_omissions = {
            operation.operation_id
            for operation in operations
            if not operation.requested_admission
            or any(
                write.path in source_paths
                or not is_under_designated_root(write.path, roots)
                for write in operation.writes
            )
        }
        assert {omission.operation_id for omission in result.omissions} == expected_omissions
        for omission in result.omissions:
            operation = next(
                item for item in operations if item.operation_id == omission.operation_id
            )
            assert omission.command_or_procedure == operation.command_or_procedure
            assert omission.reason
            assert tuple(item.path for item in omission.affected_content) == tuple(
                write.path for write in operation.writes
            )
            assert all(item.sha256 and item.size_bytes >= 0 for item in omission.affected_content)
            assert tuple(item.check_id for item in omission.dependent_checks) == (
                operation.dependent_check_ids
            )
            assert all(
                item.status is AssessmentStatus.UNVERIFIED
                for item in omission.dependent_checks
            )

        comparison = result.final_comparison
        assert comparison.tracked_paths_identical
        assert comparison.untracked_paths_identical
        assert comparison.production_bytes_identical
        assert comparison.differences == ()
        assert comparison.writes_outside_designated_roots == ()
        assert comparison.preservation_confirmed

    assert seen_terminations == set(AssessmentTermination)
