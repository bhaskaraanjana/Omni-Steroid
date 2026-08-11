"""Enforce loopback-only sockets when a child interpreter proves guard loading.

The adapter prepares a Python startup guard without treating the command name as
proof. Guarded user code is released only after the runner validates the marker.
The lease mechanism itself lives in `python_startup_guard_containment`; this module
binds it to `NetworkMode.LOOPBACK_ONLY` and owns the shared admission vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contained_process_protocols import NetworkContainmentLease
from .execution_models import CheckPlan
from .model_types import NetworkMode
from .preservation import OmissionEvidence, OmittedDependentCheck
from .python_startup_guard_containment import (
    PythonStartupGuardContainment,
)
from .python_startup_guard_containment import (
    is_guardable_python_command as is_guardable_python_command,
)

_UNAVAILABLE_REASON = (
    "empirical loopback containment is unavailable: no unique current-lease "
    "Python startup proof can be established for this command"
)


@dataclass(frozen=True, slots=True)
class NetworkContainmentAdmission:
    """Exactly one prepared proof lease or complete pre-launch omission."""

    lease: NetworkContainmentLease
    omission: OmissionEvidence | None

    def __post_init__(self) -> None:
        """Reject records that are simultaneously prepared and omitted."""
        if self.lease.enforced == (self.omission is not None):
            raise ValueError("containment admission must be prepared or omitted")

    @property
    def admitted(self) -> bool:
        """Return whether an empirical proof attempt may be launched."""
        return self.lease.enforced


class LoopbackOnlyNetworkContainment(PythonStartupGuardContainment):
    """Install one proof-producing loopback-only Python socket guard per lease."""

    required_mode = NetworkMode.LOOPBACK_ONLY
    allow_loopback = True


def establish_network_containment(
    containment: PythonStartupGuardContainment,
    plan: CheckPlan,
    ownership_token: str,
) -> NetworkContainmentAdmission:
    """Prepare an empirical-proof attempt or return complete omission evidence."""
    lease = containment.establish(plan, ownership_token)
    if lease.enforced:
        return NetworkContainmentAdmission(lease, None)
    command = plan.exact_argv.values if plan.exact_argv else plan.numbered_procedure
    omission = OmissionEvidence(
        operation_id=plan.check_id,
        command_or_procedure=command or (),
        affected_content=(),
        reason=_UNAVAILABLE_REASON,
        dependent_checks=(OmittedDependentCheck(plan.check_id),),
    )
    return NetworkContainmentAdmission(lease, omission)


def containment_unavailable_reason() -> str:
    """Return the stable fail-closed reason used by admission and reports."""
    return _UNAVAILABLE_REASON
