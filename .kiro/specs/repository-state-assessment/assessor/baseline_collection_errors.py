"""Declare the single failure type raised by read-only baseline observation.

Every baseline stage — Git observation, source-manifest hashing, and the collector
that sequences them — signals failure with the same exception. It lives in its own
module so no stage has to import a sibling stage merely to reach the error type.
"""

from __future__ import annotations


class BaselineCollectionError(RuntimeError):
    """Raised when a required read-only baseline observation cannot complete."""
