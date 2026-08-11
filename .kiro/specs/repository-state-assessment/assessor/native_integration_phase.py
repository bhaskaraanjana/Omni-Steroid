"""Task 11.6 hardware/native preflights and fail-closed scope evidence.

Every scope is preflighted independently before any scoped behavior. A scope runs
only when all of its own prerequisites were observed available; a missing
prerequisite produces `Environment_Blocked`, never a product failure. The mechanics
of running an admitted procedure live in `native_procedure_executor`.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import psutil

from .assessment_phase_gates import CheckCompletion, GateStatus, PhaseExecutionResult
from .contained_process_runner import ContainedProcessRunner
from .evidence_models import AssessmentEnvironment
from .hardware_status import HardwareCheckOutcome, HardwareScope, classify_hardware_inventory
from .host_inventory import collect_hardware_inventory, collect_operating_system_inventory
from .model_types import ZonedTimestamp
from .native_check_plans import NativeCheckPlan, build_native_check_plans
from .native_host_observations import NativeHostFacts, observations_for_scope
from .native_preflight import NativePreflightResult, preflight_native_check
from .native_procedure_executor import NativeProcedureExecutor, blocked_attempt
from .observation_support import write_json
from .observed_write_auditor import ObservedWriteAuditor

NATIVE_CHECK_IDS = tuple(f"hardware-{scope.value}" for scope in HardwareScope)
# Discovered from current repository tray configuration; kept as data, not behavior.
_TRAY_ACTIONS = ("omni-tray-show", "omni-tray-start-capture", "omni-tray-quit")
# Names whose pre-existing presence would make a native scope unsafe to exercise.
_CONFLICTING_PROCESS_NAMES = ("omni-ui.exe", "omni-engine.exe", "notepad.exe")


def execute_native_integration(
    mirror_root: Path,
    temporary_root: Path,
    output_root: Path,
    *,
    interpreter: str | None = None,
) -> PhaseExecutionResult:
    """Preflight every native scope and execute only the fully admitted ones."""
    native_root = temporary_root / "native"
    native_root.mkdir(exist_ok=False)
    facts = _collect_facts(mirror_root, temporary_root)
    plans = build_native_check_plans(
        cwd=str(mirror_root), run_root=str(native_root), tray_actions=_TRAY_ACTIONS
    )
    environment = AssessmentEnvironment(
        collect_operating_system_inventory(), collect_hardware_inventory(), (), ()
    )
    started_at = ZonedTimestamp(datetime.now().astimezone())
    artifact_reference = str((output_root / "native-integration.json").resolve(strict=False))
    # The mirror-execution phase already owns "write-audit" in this run tree; this phase
    # monitors the same tree through its own exclusive evidence root.
    auditor = ObservedWriteAuditor(temporary_root, observation_name="write-audit-native")
    executor = NativeProcedureExecutor(
        mirror_root,
        temporary_root,
        auditor,
        ContainedProcessRunner(),
        interpreter or sys.executable,
    )
    records: list[dict[str, object]] = []
    outcomes: list[HardwareCheckOutcome] = []
    for plan in plans:
        preflight = preflight_native_check(
            plan=plan,
            observations=observations_for_scope(plan.scope, facts),
            started_at=started_at,
            environment=environment,
            source_revision="assessment-mirror",
        )
        record, outcome = _resolve(plan, preflight, executor, artifact_reference)
        records.append(record)
        outcomes.append(outcome)
    inventory = classify_hardware_inventory(tuple(outcomes))
    statuses = {decision.scope: decision.primary_status.value for decision in inventory.decisions}
    for record in records:
        record["status"] = statuses[HardwareScope(str(record["scope"]))]
    payload = {
        "preflights_completed_before_scoped_behavior": True,
        "scope_count": len(records),
        "status_counts": _counts(statuses.values()),
        "audio_persisted": False,
        "downloads_performed": 0,
        "permission_or_firewall_changes": 0,
        "pre_existing_processes_touched": 0,
        "conflicting_pre_existing_processes": list(facts.conflicting_process_names),
        "product_failure_scopes": [
            scope.value for scope in inventory.product_failure_scopes
        ],
        "scopes": records,
    }
    artifact = write_json(output_root, "native-integration.json", payload)
    reference = str(artifact)
    checks = tuple(
        CheckCompletion(
            str(record["check_id"]), bool(record["execution_attempted"]), reference
        )
        for record in records
    )
    return PhaseExecutionResult(GateStatus.GREEN, (reference,), None, checks)


def _collect_facts(mirror_root: Path, temporary_root: Path) -> NativeHostFacts:
    running = set()
    for process in psutil.process_iter(["name"]):
        name = (process.info.get("name") or "").casefold()
        if name in _CONFLICTING_PROCESS_NAMES:
            running.add(name)
    return NativeHostFacts(
        mirror_root=mirror_root,
        contained_models_dir=temporary_root / "process-data",
        interactive_desktop=bool(os.environ.get("SESSIONNAME")),
        conflicting_process_names=tuple(sorted(running)),
        graphics_processor_tool=_graphics_processor_tool(),
        tray_actions=_TRAY_ACTIONS,
    )


def _graphics_processor_tool() -> str | None:
    """Resolve a vendor management tool on PATH without executing it."""
    for name in ("nvidia-smi.exe", "nvidia-smi"):
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            if directory and (Path(directory) / name).is_file():
                return str(Path(directory) / name)
    return None


def _resolve(
    plan: NativeCheckPlan,
    preflight: NativePreflightResult,
    executor: NativeProcedureExecutor,
    evidence_ref: str,
) -> tuple[dict[str, object], HardwareCheckOutcome]:
    base: dict[str, object] = {
        "scope": plan.scope.value,
        "check_id": plan.check_plan.check_id,
        "applicability": plan.check_plan.applicability.value,
        "prerequisites_available": preflight.ready_for_scoped_behavior,
        "numbered_procedure": list(plan.check_plan.numbered_procedure or ()),
        "observables": [asdict(item) for item in plan.observables],
        "exactly_once_operations": list(plan.exactly_once_operations),
        "safety": asdict(plan.safety),
        "timeout_ms": plan.check_plan.timeout_ms,
        "preflight": [
            {
                "prerequisite": item.prerequisite_name,
                "available": item.available,
                "detection_evidence": item.detection_evidence,
                "detection_detail": item.detection_detail,
                "scoped_behavior_executed": item.scoped_behavior_executed,
            }
            for item in preflight.observations
        ],
        "evidence_ref": evidence_ref,
    }
    attempt = (
        executor.run(plan, preflight.resolved_plan)
        if preflight.ready_for_scoped_behavior
        else _blocked_by_preflight(preflight)
    )
    base.update(attempt)
    outcome = HardwareCheckOutcome(
        scope=plan.scope,
        applicability=plan.check_plan.applicability,
        prerequisites_available=preflight.ready_for_scoped_behavior,
        execution_attempted=bool(attempt["execution_attempted"]),
        required_outcomes_complete=bool(attempt.get("required_outcomes_complete", False)),
        subset_verified=False,
        malfunction_observed=bool(attempt.get("malfunction_observed", False)),
        evidence_ref=evidence_ref,
    )
    return base, outcome


def _blocked_by_preflight(preflight: NativePreflightResult) -> dict[str, object]:
    unavailable = tuple(
        item.prerequisite_name for item in preflight.observations if not item.available
    )
    return blocked_attempt(f"unavailable prerequisite: {', '.join(unavailable)}")


def _counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))
