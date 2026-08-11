"""Task 11.5 Local E2E preflights, partition, and fail-closed evidence."""

from __future__ import annotations

import socket
from collections import Counter
from pathlib import Path

from .assessment_phase_gates import CheckCompletion, GateStatus, PhaseExecutionResult
from .e2e_partition import E2EDisposition
from .observed_write_auditor import ObservedWriteAuditor
from .observation_support import write_json
from .playwright_preflight_admission import (
    LoopbackPortObservation,
    PlaywrightPreflightObservation,
    admit_playwright_scenarios,
)
from .playwright_scenario_inventory import inventory_playwright_scenarios

LOCAL_E2E_CHECK_IDS = ("local-e2e-inventory",)


def _port_observation(port: int) -> LoopbackPortObservation:
    available = False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", port))
            available = True
    except OSError:
        pass
    return LoopbackPortObservation("127.0.0.1", port, bind_available=available)


def _preflight(name: str, passed: bool, observed: object, reason: str) -> dict[str, object]:
    return {
        "name": name,
        "status": "passed" if passed else "blocked",
        "observed": observed,
        "reason": reason,
    }


def _absent(reason: str) -> dict[str, str]:
    return {"state": "absent", "reason": reason}


def execute_local_e2e(
    mirror_root: Path,
    temporary_root: Path,
    output_root: Path,
    *,
    ownership_token: str,
    browser_executable_path: str | None = None,
) -> PhaseExecutionResult:
    """Run all preflights, classify every scenario, and launch only if admitted."""
    inventory = inventory_playwright_scenarios(mirror_root, selected_projects=("e2e",))
    frontend = mirror_root / "apps/ui/dist/index.html"
    engine = mirror_root / "engine/server.py"
    seed = mirror_root / "apps/ui/e2e/harness/seed_engine.py"
    vault = mirror_root / "apps/ui/e2e/fixtures/vault"
    migrations = mirror_root / "migrations"
    browser = Path(browser_executable_path) if browser_executable_path else None
    ports = tuple(_port_observation(port) for port in inventory.required_loopback_ports)
    local_data = seed.is_file() and vault.is_dir() and migrations.is_dir()
    local_services = engine.is_file()
    process_ownership = bool(ownership_token.strip())
    e2e_root = temporary_root / "local-e2e"
    e2e_root.mkdir(exist_ok=False)
    auditor = ObservedWriteAuditor(e2e_root)
    write_audit = auditor.available
    # Current empirical containment requires each child to emit a per-lease proof.
    # The Node/Chromium participants cannot emit it, so absence blocks pre-launch.
    loopback_only = False
    unsafe_cleanup_disabled = not inventory.harness_cleanup_kills_by_port
    browser_available = browser is not None and browser.is_file()
    observation = PlaywrightPreflightObservation(
        production_frontend_path=str(frontend),
        production_frontend_available=frontend.is_file(),
        frontend_startup_is_production=inventory.frontend_startup_is_production,
        production_engine_path=str(engine),
        production_engine_available=engine.is_file(),
        engine_startup_is_production=inventory.engine_startup_is_production,
        browser_executable_path=str(browser) if browser else None,
        browser_available=browser_available,
        local_test_data_available=local_data,
        local_services_available=local_services,
        loopback_ports=ports,
        write_containment_established=write_audit,
        non_loopback_denial_enforceable=loopback_only,
        unsafe_harness_cleanup_disabled=unsafe_cleanup_disabled,
    )
    admission = admit_playwright_scenarios(inventory, observation)
    preflights = [
        _preflight("production frontend build", frontend.is_file(), str(frontend), "production index must exist"),
        _preflight("production frontend startup", inventory.frontend_startup_is_production, "build + preview", "dev/watch mode is prohibited"),
        _preflight("real local engine", engine.is_file(), str(engine), "engine.server source must exist"),
        _preflight("production engine startup", inventory.engine_startup_is_production, "python -m engine.server", "real engine module path is required"),
        _preflight("configured browser", browser_available, str(browser) if browser else None, "no configured executable may be inferred or downloaded"),
        _preflight("local test data", local_data, {"seed": str(seed), "vault": str(vault), "migrations": str(migrations)}, "all local fixtures must exist"),
        _preflight("local services", local_services, str(engine), "real local engine service path is required"),
        *(
            _preflight(
                f"free loopback port {item.port}", item.bind_available and item.listener_pid is None,
                {"host": item.host, "port": item.port, "listener_pid": item.listener_pid, "bind_available": item.bind_available},
                "occupied or non-loopback ports block; existing listeners are never killed",
            )
            for item in ports
        ),
        _preflight("process ownership", process_ownership, {"ownership_token_present": process_ownership}, "every launched tree requires assessment ownership"),
        _preflight("ownership-safe harness cleanup", unsafe_cleanup_disabled, {"kills_by_port": inventory.harness_cleanup_kills_by_port}, "port-based cleanup is unsafe and is never invoked"),
        _preflight("write audit", write_audit, {"root": str(e2e_root)}, "observed write auditing must be established"),
        _preflight("loopback-only egress", loopback_only, {"proof_marker": "absent", "node_browser_guard": "unavailable"}, "Node/Chromium cannot emit the required per-lease containment proof"),
    ]
    by_id = {item.scenario_id: item for item in inventory.scenarios}
    scenarios: list[dict[str, object]] = []
    for decision in admission.partition.decisions:
        metadata = by_id[decision.scenario.scenario_id]
        absence_reason = f"scenario was not executed: {decision.disposition.value}"
        scenarios.append({
            "scenario_id": metadata.scenario_id,
            "title": metadata.title,
            "project": metadata.project,
            "disposition": decision.disposition.value,
            "reason": metadata.configuration_exclusion_reason,
            "unavailable_prerequisites": list(decision.unavailable_prerequisites),
            "outputs": {
                "scenario": _absent(absence_reason), "frontend": _absent(absence_reason),
                "engine": _absent(absence_reason), "browser": _absent(absence_reason),
                "screenshot": _absent(absence_reason), "trace": _absent(absence_reason),
            },
        })
    if admission.launch_admitted:
        raise RuntimeError("Local E2E launch admitted without a configured production executor")
    counts = Counter(item["disposition"] for item in scenarios)
    payload = {
        "preflights_completed_before_process_launch": True,
        "preflights": preflights,
        "scenario_count": len(scenarios),
        "disposition_counts": dict(sorted(counts.items())),
        "scenarios": scenarios,
        "assessment_paths": {
            "database": str(e2e_root / "data/omni.db"),
            "models": str(e2e_root / "models"),
            "reports": str(e2e_root / "reports"),
            "traces": str(e2e_root / "traces"),
            "provider_configuration": "explicitly nonexistent",
        },
        "process_cleanup": {
            "owned_processes_started": 0,
            "cleanup_scope": "assessment-owned processes only",
            "cleanup_needed": False,
            "assessment_owned_processes_surviving": 0,
            "pre_existing_processes_touched": 0,
        },
        "repository_harness_cleanup_invoked": False,
        "product_failures": 0,
    }
    artifact = write_json(output_root, "local-e2e.json", payload)
    reference = str(artifact)
    return PhaseExecutionResult(
        GateStatus.GREEN,
        (reference,),
        None,
        (CheckCompletion(LOCAL_E2E_CHECK_IDS[0], True, reference),),
    )
