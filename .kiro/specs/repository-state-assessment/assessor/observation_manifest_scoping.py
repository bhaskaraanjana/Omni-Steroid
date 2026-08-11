"""Keep the assessment's own output out of the workspace it is measuring.

A run writes into `assessment-output`, so those paths must be excluded from the
baseline and final manifests. Without this the assessment would observe its own
writes and report the workspace as modified by itself.
"""

from __future__ import annotations

from dataclasses import replace

from .baseline_models import FileManifest
from .observation_support import MIRROR_EXCLUDED_PREFIXES


def is_assessment_output(path: str) -> bool:
    """Return whether a manifest path belongs to the assessment's own output root."""
    normalized = path.replace("\\", "/")
    prefix = MIRROR_EXCLUDED_PREFIXES[-1]
    return normalized == prefix or normalized.startswith(prefix + "/")


def without_assessment_outputs(manifest: FileManifest) -> FileManifest:
    """Drop the assessment's own output entries from a collected manifest."""
    return replace(
        manifest,
        entries=tuple(
            entry for entry in manifest.entries if not is_assessment_output(entry.path)
        ),
    )
