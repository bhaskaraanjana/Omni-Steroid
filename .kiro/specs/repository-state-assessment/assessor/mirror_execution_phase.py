"""Execute Task 11.4 checks once inside the verified assessment mirror.

Only commands with complete local prerequisites and empirical Python containment
are admitted. Raw output remains quarantined under the temporary run root.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .assessment_phase_gates import CheckCompletion, GateStatus, PhaseExecutionResult
from .contained_process_runner import ContainedProcessRunner, RunnerContext
from .contained_runner_support import ProcessRunBlocked
from .discovery_models import DiscoveryOutcome, RepositoryDiscoveryReport, ToolResolution
from .execution_models import Applicability, CheckPlan, Prerequisite, TerminationKind
from .loopback_only_network_containment import (
    LoopbackOnlyNetworkContainment,
    is_guardable_python_command,
)
from .model_types import (
    ExactArgumentVector,
    NetworkMode,
    NetworkPolicy,
    VerificationPlane,
    WritePolicy,
)
from .observed_write_auditor import ObservedWriteAuditor
from .observation_support import write_json
from .preservation import PlannedOperation
from .summary_parser import parse_test_summary
from .write_admission import WriteAdmissionRequest, evaluate_write_admission

TASK_11_4_CHECK_IDS = (
    "python-lint", "python-types", "python-tests", "python-coverage",
    "typescript-types", "typescript-tests", "typescript-coverage", "rust-check",
    "rust-tests", "engine-build", "frontend-build", "desktop-build",
    "frozen-engine-smoke", "packaging", "hermetic-security",
)

_PLANES = {
    "python": VerificationPlane.PYTHON_ENGINE,
    "typescript": VerificationPlane.TYPESCRIPT_UI,
    "rust": VerificationPlane.RUST_TAURI_SHELL,
    "engine-build": VerificationPlane.PRODUCT_BUILD,
    "frontend-build": VerificationPlane.PRODUCT_BUILD,
    "desktop-build": VerificationPlane.PRODUCT_BUILD,
}


@dataclass(frozen=True, slots=True)
class _Attempt:
    record: dict[str, object]
    executed: bool


def execute_mirror_checks(
    mirror_root: Path,
    temporary_root: Path,
    output_root: Path,
    report: RepositoryDiscoveryReport,
) -> PhaseExecutionResult:
    """Resolve every Task 11.4 check to one attempt or one explicit omission."""
    outcomes = {item.check_id: item for item in report.outcomes}
    resolutions = {item.name: item for item in report.tool_resolutions}
    auditor = ObservedWriteAuditor(temporary_root)
    runner = ContainedProcessRunner()
    records: list[dict[str, object]] = []
    executed: set[str] = set()
    for check_id in TASK_11_4_CHECK_IDS:
        outcome = outcomes.get(check_id)
        if outcome is None:
            attempt = _Attempt(_omission(check_id, "not implemented", (
                "no executable path found by the complete repository configuration search",
            )), False)
        else:
            attempt = _run_or_omit(
                outcome, resolutions, mirror_root, temporary_root, auditor, runner
            )
        records.append(attempt.record)
        if attempt.executed:
            executed.add(check_id)
    aggregate = _aggregate_build(records)
    payload = {
        "checks": records,
        "aggregate_build": aggregate,
        "coverage": _coverage(records),
        "reconciliation": {
            "committed": {
                "tests": 1358,
                "line_coverage_percent": "86.7",
                "branch_coverage_percent": "78.2",
            },
            "fresh": _fresh_metrics(records),
            "historical_values_preserved": True,
        },
    }
    artifact = write_json(output_root, "mirror-execution.json", payload)
    reference = str(artifact)
    checks = tuple(
        CheckCompletion(check_id, check_id in executed, reference)
        for check_id in TASK_11_4_CHECK_IDS
    )
    return PhaseExecutionResult(GateStatus.GREEN, (reference,), None, checks)


def _run_or_omit(
    outcome: DiscoveryOutcome,
    resolutions: dict[str, ToolResolution],
    mirror: Path,
    temporary: Path,
    auditor: ObservedWriteAuditor,
    runner: ContainedProcessRunner,
) -> _Attempt:
    command = outcome.command
    if command is None:
        return _Attempt(_omission(outcome.check_id, "not implemented", (
            "no executable path found by the complete repository configuration search",
        )), False)
    missing = tuple(
        name for name in command.required_tools
        if name not in resolutions or not resolutions[name].available
    )
    if missing:
        return _Attempt(_omission(outcome.check_id, "blocked", (
            f"named prerequisite unavailable: {', '.join(missing)}",
        ), command.argv), False)
    argv = _contained_argv(command.argv)
    if argv is None:
        reason = (
            "dependency installation or synchronization is prohibited"
            if _would_install(command.argv)
            else "command cannot emit the required empirical Python containment proof"
        )
        return _Attempt(_omission(outcome.check_id, "blocked", (reason,), command.argv), False)
    plan = _plan(outcome, argv, mirror, temporary)
    environment = _safe_environment(resolutions, command.required_tools)
    context = RunnerContext(
        temporary, mirror, environment, _write_admission(plan), auditor,
        LoopbackOnlyNetworkContainment(temporary),
    )
    try:
        raw = runner.run(plan, context)
    except ProcessRunBlocked as error:
        return _Attempt(_omission(
            outcome.check_id, "blocked", (str(error),), command.argv
        ), False)
    output = _raw_output(temporary, raw.stdout_ref, raw.stderr_ref)
    parsed = parse_test_summary(output, assessed_scope=plan.scope)
    status = _status(raw.termination.kind, raw.termination.exit_code)
    record = {
        "check_id": outcome.check_id,
        "status": status,
        "attempt_count": 1,
        "discovered_argv": list(command.argv),
        "executed_argv": list(argv),
        "duration_ms": raw.duration_ms,
        "termination": raw.termination.kind.value,
        "exit_code": raw.termination.exit_code,
        "test_counts": asdict(parsed.test_counts),
        "warning_count": parsed.warning_count,
        "warnings": list(parsed.warnings),
        "measurements": [
            {"name": item.name, "value": str(item.value), "unit": item.unit.value}
            for item in parsed.measurements
        ],
        "stdout_ref": raw.stdout_ref,
        "stderr_ref": raw.stderr_ref,
        "network_observation_ref": raw.network_observation_ref,
        "write_audit_ref": raw.write_audit_ref,
        "blockers": [],
    }
    return _Attempt(record, True)


def _plan(outcome: DiscoveryOutcome, argv: tuple[str, ...], mirror: Path, temporary: Path) -> CheckPlan:
    command = outcome.command
    if command is None:
        raise ValueError("an executable plan requires a discovered command")
    prerequisites = tuple(
        Prerequisite(name, ("complete PATH/PATHEXT search",), True)
        for name in command.required_tools
    )
    timeout = 1_800_000 if outcome.check_id == "python-tests" else 600_000
    return CheckPlan(
        outcome.check_id, _plane(outcome.check_id), outcome.check_id,
        command.sources[0], ExactArgumentVector(argv), None,
        str((mirror / command.cwd).resolve(strict=True)), prerequisites,
        Applicability.APPLICABLE, "current repository configuration", timeout,
        WritePolicy((str(temporary / "process-data"),)),
        NetworkPolicy(NetworkMode.LOOPBACK_ONLY), False, (), (),
    )


def _write_admission(plan: CheckPlan):
    operation = PlannedOperation(plan.check_id, plan.exact_argv.values, True, ())
    return evaluate_write_admission(WriteAdmissionRequest(
        operation, plan.write_policy, True, True, (),
    ))


def _contained_argv(argv: tuple[str, ...]) -> tuple[str, ...] | None:
    if _would_install(argv):
        return None
    if Path(argv[0]).name.casefold() in {"cmd", "cmd.exe"}:
        return None
    if not is_guardable_python_command(argv):
        return None
    if len(argv) >= 3 and Path(argv[0]).name.casefold() in {"uv", "uv.exe"} and argv[1] == "run":
        return (argv[0], "run", "--active", "--no-sync", *argv[2:])
    return argv


def _would_install(argv: tuple[str, ...]) -> bool:
    lowered = tuple(value.casefold() for value in argv)
    return any(value in {"install", "sync", "--with"} for value in lowered)


def _safe_environment(
    resolutions: dict[str, ToolResolution], required_tools: tuple[str, ...]
) -> dict[str, str]:
    environment = dict(os.environ)
    for name in required_tools:
        resolution = resolutions.get(name)
        if resolution and resolution.executable_path and name in {"mypy", "pytest"}:
            environment["VIRTUAL_ENV"] = str(Path(resolution.executable_path).parent.parent)
            break
    return environment


def _raw_output(root: Path, stdout_ref: str | None, stderr_ref: str | None) -> str:
    chunks = []
    for reference in (stdout_ref, stderr_ref):
        if reference:
            chunks.append((root / reference).read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def _status(kind: TerminationKind, exit_code: int | None) -> str:
    if kind is TerminationKind.TIMED_OUT:
        return "timed out"
    if kind is TerminationKind.EXITED and exit_code == 0:
        return "passed"
    return "failed"


def _plane(check_id: str) -> VerificationPlane:
    for prefix, plane in _PLANES.items():
        if check_id.startswith(prefix):
            return plane
    return VerificationPlane.PRODUCT_BUILD


def _omission(
    check_id: str, status: str, blockers: tuple[str, ...], argv: tuple[str, ...] = ()
) -> dict[str, object]:
    return {
        "check_id": check_id, "status": status, "attempt_count": 0,
        "discovered_argv": list(argv), "executed_argv": [], "duration_ms": 0,
        "termination": "precheck_blocked" if status == "blocked" else "omitted",
        "exit_code": None,
        "test_counts": {name: 0 for name in (
            "passed", "failed", "skipped", "deselected", "ignored"
        )},
        "warning_count": 0, "warnings": [], "measurements": [],
        "stdout_ref": None, "stderr_ref": None, "network_observation_ref": None,
        "write_audit_ref": None, "blockers": list(blockers),
    }


def _fresh_metrics(records: list[dict[str, object]]) -> dict[str, object]:
    tests = next(item for item in records if item["check_id"] == "python-tests")
    measurements = {item["name"]: item["value"] for item in tests["measurements"]}
    return {
        "tests": tests["test_counts"] if tests["attempt_count"] else None,
        "line_coverage_percent": measurements.get("lines_coverage"),
        "branch_coverage_percent": measurements.get("branches_coverage"),
    }


def _coverage(records: list[dict[str, object]]) -> dict[str, object]:
    fresh = _fresh_metrics(records)
    return {
        "line_percent": fresh["line_coverage_percent"],
        "branch_percent": fresh["branch_coverage_percent"],
        "line_measured": fresh["line_coverage_percent"] is not None,
        "branch_measured": fresh["branch_coverage_percent"] is not None,
    }


def _aggregate_build(records: list[dict[str, object]]) -> dict[str, object]:
    components = [
        item for item in records
        if item["check_id"] in {"engine-build", "frontend-build", "desktop-build"}
    ]
    failed = any(item["status"] in {"failed", "timed out"} for item in components)
    passed = all(item["status"] == "passed" for item in components)
    status = "failed" if failed else "passed" if passed else "unverified"
    return {"status": status, "passed": passed, "components": components}
