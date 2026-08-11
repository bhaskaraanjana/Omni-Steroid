"""Refuse a run whose roots could let the assessment write outside its own space.

These are containment preconditions, not conveniences. Execution must happen outside
the workspace being measured, published output must land only under the spec's
assessment-output directory, and the two roots must never overlap.
"""

from __future__ import annotations

from pathlib import Path

ASSESSMENT_OUTPUT_RELATIVE = ".kiro/specs/repository-state-assessment/assessment-output"


def validate_assessment_roots(
    *, source: Path, temporary: Path, output: Path, manifest_path: Path
) -> None:
    """Raise unless every root satisfies its containment precondition."""
    allowed_output = (source / ASSESSMENT_OUTPUT_RELATIVE).resolve(strict=True)
    if not output.is_relative_to(allowed_output):
        raise ValueError("output root is outside assessment-output")
    if temporary.is_relative_to(source):
        raise ValueError("temporary execution root must be outside the source workspace")
    if output.is_relative_to(temporary) or temporary.is_relative_to(output):
        raise ValueError("temporary and permanent roots must be disjoint")
    if not manifest_path.resolve(strict=False).is_relative_to(output):
        raise ValueError("run manifest must be inside the output root")
