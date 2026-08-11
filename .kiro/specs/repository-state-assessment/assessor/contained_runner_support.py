"""Fail-closed path and identifier helpers for the contained runner."""

from __future__ import annotations

import re
from pathlib import Path

_SAFE_FILE_PART = re.compile(r"[^A-Za-z0-9._-]+")


class ProcessRunBlocked(RuntimeError):
    """Raised when required containment proof is absent before result admission."""


def existing_directory(path: Path, label: str) -> Path:
    """Resolve one real directory without accepting symbolic redirection."""
    candidate = Path(path)
    if candidate.is_symlink():  # Control: reject directory redirection.
        raise ProcessRunBlocked(f"{label} must not be a symbolic link: {path}")
    try:
        resolved = candidate.resolve(strict=True)  # Control: existing canonical directory.
    except OSError as error:
        raise ProcessRunBlocked(f"{label} is unavailable: {path}") from error
    if not resolved.is_dir():  # Control: files cannot stand in for containment roots.
        raise ProcessRunBlocked(f"{label} must be a real directory: {path}")
    return resolved


def safe_file_part(value: str) -> str:
    """Return a bounded path component derived from an untrusted check ID."""
    sanitized = _SAFE_FILE_PART.sub("-", value).strip(".-")  # Control: safe evidence name.
    return sanitized[:80] or "check"  # Control: bounded non-empty evidence name.
