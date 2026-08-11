"""Apply production network containment during repository command admission."""

from __future__ import annotations

from pathlib import Path

from .discovery_models import DiscoveredCommand
from .execution_models import Applicability, CheckPlan
from .loopback_only_network_containment import (
    LoopbackOnlyNetworkContainment,
    establish_network_containment,
)
from .model_types import (
    ExactArgumentVector,
    NetworkMode,
    NetworkPolicy,
    VerificationPlane,
    WritePolicy,
)
from .preservation import OmissionEvidence


def probe_discovered_containment(
    containment: LoopbackOnlyNetworkContainment,
    commands: tuple[DiscoveredCommand, ...],
    mirror_root: Path,
    temporary_root: Path,
) -> tuple[tuple[str, ...], tuple[OmissionEvidence, ...]]:
    """Return proof-attempt candidates plus complete pre-launch omissions."""
    candidates: list[str] = []
    omissions: list[OmissionEvidence] = []
    for index, command in enumerate(commands):
        plan = _containment_plan(command, mirror_root, temporary_root)
        admission = establish_network_containment(
            containment, plan, f"admission-{index}"
        )
        containment.release(admission.lease)  # Control: release this probe only.
        if admission.admitted:
            candidates.append(command.check_id)
        elif admission.omission is not None:
            omissions.append(admission.omission)
    return tuple(candidates), tuple(omissions)


def _containment_plan(
    command: DiscoveredCommand, mirror_root: Path, temporary_root: Path
) -> CheckPlan:
    return CheckPlan(
        check_id=command.check_id,
        plane=VerificationPlane.PYTHON_ENGINE,
        scope=f"discovered command: {command.check_id}",
        command_source=command.sources[0] if command.sources else None,
        exact_argv=ExactArgumentVector(command.argv),
        numbered_procedure=None,
        cwd=str((mirror_root / command.cwd).resolve(strict=False)),
        prerequisites=(),
        applicability=Applicability.APPLICABLE,
        applicability_basis="current repository discovery",
        timeout_ms=1,
        write_policy=WritePolicy((str(temporary_root / "process-data"),)),
        network_policy=NetworkPolicy(NetworkMode.LOOPBACK_ONLY),
        external_dependency=False,
        dependent_check_ids=(),
        cleanup_procedure=("terminate assessment-owned process tree",),
    )
