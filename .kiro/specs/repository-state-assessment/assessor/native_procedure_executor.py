"""Execute one bounded native procedure under full assessment containment.

Separated from the phase so the decision to run is distinct from the mechanics of
running. Every path out of here is either one real attempt record or one explicit
omission: a containment refusal and a launch failure are assessment omissions, never
product malfunctions, and only a procedure that genuinely started may be called one.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .contained_process_runner import ContainedProcessRunner, RunnerContext
from .contained_runner_support import ProcessRunBlocked
from .execution_models import (
    Applicability,
    CheckPlan,
    Prerequisite,
    TerminationKind,
)
from .model_types import ExactArgumentVector, NetworkMode, NetworkPolicy, WritePolicy
from .native_bounded_procedures import procedure_source
from .native_check_plans import NativeCheckPlan
from .no_egress_network_containment import (
    NO_EGRESS_UNAVAILABLE_REASON,
    NoEgressNetworkContainment,
)
from .observed_write_auditor import ObservedWriteAuditor
from .preservation import PlannedOperation
from .write_admission import (
    WriteAdmissionDecision,
    WriteAdmissionRequest,
    evaluate_write_admission,
)

CONTAINMENT_DENIAL = "egress denied by assessment containment"


def blocked_attempt(reason: str) -> dict[str, object]:
    """Return the record for a scope that never executed, with its exact reason."""
    return {
        "execution_attempted": False,
        "executed_argv": [],
        "duration_ms": 0,
        "termination": TerminationKind.PRECHECK_BLOCKED.value,
        "exit_code": None,
        "result": None,
        "malfunction_observed": False,
        "required_outcomes_complete": False,
        "stdout_ref": None,
        "stderr_ref": None,
        "write_audit_ref": None,
        "network_observation_ref": None,
        "blockers": [reason],
    }


class NativeProcedureExecutor:
    """Run one bounded native procedure once, inside the verified mirror."""

    def __init__(
        self,
        mirror_root: Path,
        temporary_root: Path,
        auditor: ObservedWriteAuditor,
        runner: ContainedProcessRunner,
        interpreter: str,
    ) -> None:
        self._mirror = mirror_root
        self._temporary = temporary_root
        self._auditor = auditor
        self._runner = runner
        self._interpreter = interpreter

    def run(self, plan: NativeCheckPlan, resolved: CheckPlan) -> dict[str, object]:
        """Return one attempt record, or one blocked record when execution is refused."""
        source = procedure_source(plan.scope)
        if source is None:
            return blocked_attempt(
                "the assessment has no bounded procedure that can exercise this scope "
                "without launching the product's desktop application"
            )
        argv = (self._interpreter, "-c", source)
        executable = _executable_plan(resolved, argv, self._temporary)
        context = RunnerContext(
            self._temporary,
            self._mirror,
            dict(os.environ),
            _write_admission(executable),
            self._auditor,
            NoEgressNetworkContainment(self._temporary),
        )
        try:
            raw = self._runner.run(executable, context)
        except ProcessRunBlocked as error:
            return blocked_attempt(f"{NO_EGRESS_UNAVAILABLE_REASON}: {error}")
        except OSError as error:
            # An assessment-side launch failure is an omission, not a product malfunction.
            return blocked_attempt(f"the bounded procedure could not be launched: {error}")
        output = _read(self._temporary, raw.stdout_ref)
        errors = _read(self._temporary, raw.stderr_ref)
        if CONTAINMENT_DENIAL in errors:
            # Containment denial is an assessment omission, never a product malfunction.
            return blocked_attempt(
                "the procedure attempted egress and was denied by containment"
            )
        exited_clean = (
            raw.termination.kind is TerminationKind.EXITED and raw.termination.exit_code == 0
        )
        parsed = _parse(output) if exited_clean else None
        return {
            "execution_attempted": True,
            "executed_argv": [argv[0], "-c", "<assessment bounded procedure>"],
            "duration_ms": raw.duration_ms,
            "termination": raw.termination.kind.value,
            "exit_code": raw.termination.exit_code,
            "result": parsed,
            "malfunction_observed": not exited_clean,
            "required_outcomes_complete": exited_clean and parsed is not None,
            "stdout_ref": raw.stdout_ref,
            "stderr_ref": raw.stderr_ref,
            "write_audit_ref": raw.write_audit_ref,
            "network_observation_ref": raw.network_observation_ref,
            "blockers": [] if exited_clean else ["procedure did not terminate successfully"],
        }


def _executable_plan(
    resolved: CheckPlan, argv: tuple[str, ...], temporary: Path
) -> CheckPlan:
    prerequisites = tuple(
        Prerequisite(item.name, item.detection_procedure, True, item.evidence_ref)
        for item in resolved.prerequisites
    )
    return CheckPlan(
        resolved.check_id,
        resolved.plane,
        resolved.scope,
        None,
        ExactArgumentVector(argv),
        None,
        resolved.cwd,
        prerequisites,
        Applicability.APPLICABLE,
        resolved.applicability_basis,
        resolved.timeout_ms,
        WritePolicy((str(temporary / "process-data"),)),
        NetworkPolicy(NetworkMode.NONE),
        False,
        resolved.dependent_check_ids,
        resolved.cleanup_procedure,
    )


def _write_admission(plan: CheckPlan) -> WriteAdmissionDecision:
    if plan.exact_argv is None:
        raise ValueError("an executable native plan requires exact argv")
    operation = PlannedOperation(plan.check_id, plan.exact_argv.values, True, ())
    return evaluate_write_admission(
        WriteAdmissionRequest(operation, plan.write_policy, True, True, ())
    )


def _read(root: Path, reference: str | None) -> str:
    if not reference:
        return ""
    return (root / reference).read_text(encoding="utf-8", errors="replace")


def _parse(output: str) -> dict[str, object] | None:
    """Read the last JSON object a procedure printed, or nothing if it printed none."""
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                return None
            return value if isinstance(value, dict) else None
    return None
