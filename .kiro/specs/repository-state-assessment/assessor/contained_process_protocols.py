"""Protocols and immutable outcomes required by the contained process runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .execution_models import CheckPlan


@dataclass(frozen=True, slots=True)
class NetworkContainmentLease:
    """Pre-launch guard plus optional empirical startup-proof handshake."""

    enforced: bool
    observation_ref: str | None
    environment_updates: tuple[tuple[str, str], ...] = ()
    proof_required: bool = False
    proof_token: str | None = None
    release_ref: str | None = None


class NetworkContainment(Protocol):
    """An externally established per-process network-denial facility."""

    def establish(
        self, plan: CheckPlan, ownership_token: str
    ) -> NetworkContainmentLease:
        """Establish denial before launch without changing command semantics."""

    def release(self, lease: NetworkContainmentLease) -> None:
        """Release only containment created for this command."""


@dataclass(frozen=True, slots=True)
class WriteAuditOutcome:
    """Post-run proof that observed writes remained in designated roots."""

    compliant: bool
    audit_ref: str | None


class WriteAuditor(Protocol):
    """A complete owned-tree write-audit facility required for launch."""

    available: bool

    def start(self, plan: CheckPlan, ownership_token: str) -> object:
        """Begin auditing before process creation."""

    def finish(self, handle: object) -> WriteAuditOutcome:
        """Stop auditing after cleanup and classify every observed write."""
