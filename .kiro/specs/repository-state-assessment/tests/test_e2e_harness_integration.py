"""Task 5.5 local-fixture E2E harness integration tests.
Validates: Requirements 4.1, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10.
"""
from __future__ import annotations
import os
import socket
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from threading import Event
import pytest
from assessor.e2e_orchestration import E2ECommand, E2EOrchestrationPlan, orchestrate_owned_e2e
from assessor.e2e_partition import E2EDisposition, E2EPartition
from assessor.e2e_process_controller import (
    E2EProcessHandle,
    E2EProcessRole,
    SubprocessOwnedE2EController,
)
from assessor.model_types import ExactArgumentVector, NetworkMode, NetworkPolicy
from assessor.playwright_preflight_admission import (
    LoopbackPortObservation,
    PlaywrightAdmissionResult,
    PlaywrightPreflightObservation,
    admit_playwright_scenarios,
)
from assessor.playwright_scenario_inventory import PlaywrightScenarioInventory, inventory_playwright_scenarios
from assessor.process_cleanup import CleanupMode
class _Controller(SubprocessOwnedE2EController):
    def __init__(self, *, abort: bool = False) -> None:
        super().__init__(poll_interval_seconds=0.005)
        self.abort = abort
        self.started: list[E2EProcessHandle] = []
        self.processes: list[subprocess.Popen[bytes]] = []
        self.wait_timeout_ms: int | None = None
        self.cleanup_mode: CleanupMode | None = None
    def start(self, role, command, environment, stdout_path, stderr_path, ownership_token):
        handle = super().start(role, command, environment, stdout_path, stderr_path, ownership_token)
        self.started.append(handle)
        self.processes.append(self._processes[handle])
        return handle
    def wait(self, handle, timeout_ms):
        self.wait_timeout_ms = timeout_ms
        if self.abort:
            raise KeyboardInterrupt
        return super().wait(handle, timeout_ms)
    def cleanup(self, handles, ownership_token, mode):
        self.cleanup_mode = mode
        return super().cleanup(handles, ownership_token, mode)
def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
def _fixture(tmp_path: Path, *, ports=(4173, 8765), scenarios=True):
    run = tmp_path / "rún root with spaces"
    mirror = run / "mirror Ω"
    (mirror / "apps/ui/dist").mkdir(parents=True)
    _write(
        mirror,
        "apps/ui/e2e/playwright.config.ts",
        'projects: [{ name: "e2e", testMatch: /.*\\.spec\\.ts/ }],\n'
        'webServer: { command: "npm run build && npm run preview -- --host 127.0.0.1" },\n',
    )
    if scenarios:
        _write(
            mirror,
            "apps/ui/e2e/specs/local ü.spec.ts",
            'test("local shell α", async ({ page }) => { await page.goto("/"); });\n'
            'test("provider answer β", async ({ page }) => {\n'
            ' await page.keyboard.press("Enter");\n'
            ' await page.getByRole("article", { name: "Answer" }).waitFor();\n});\n',
        )
    constants = "\n".join(
        f"export const {'PREVIEW' if index == 0 else 'ENGINE'}_PORT = {port};"
        for index, port in enumerate(ports)
    )
    _write(mirror, "apps/ui/e2e/harness/e2e-env.ts", constants)
    _write(mirror, "apps/ui/e2e/harness/engine-process.ts", 'spawn(PYTHON, ["-m", "engine.server"]);\n')
    _write(mirror, "engine/server.py", "# synthetic production engine\n")
    browser = _write(mirror, "browsers/browser ü.exe", "synthetic configured browser\n")
    worker = _write(
        mirror,
        "fixture worker Ω.py",
        "from pathlib import Path\nimport os, sys, threading\n"
        "role, action, artifacts, marker = sys.argv[1:5]\n"
        "Path(marker).write_text(role, encoding='utf-8')\n"
        "print(f'{role}:{action}:{artifacts}', flush=True)\n"
        "print(f'{role}-diagnostic', file=sys.stderr, flush=True)\n"
        "if role == 'browser' and artifacts in {'screenshot', 'both'}:\n"
        " Path(os.environ['OMNI_E2E_SCREENSHOT_DIR'], 'shot ü.png').write_bytes(b'png')\n"
        "if role == 'browser' and artifacts == 'both':\n"
        " Path(os.environ['OMNI_E2E_TRACE_DIR'], 'trace Ω.zip').write_bytes(b'trace')\n"
        "if action == 'success': raise SystemExit(0)\n"
        "if action == 'failure': raise SystemExit(7)\nthreading.Event().wait()\n",
    )
    inventory = inventory_playwright_scenarios(mirror, selected_projects=("e2e",))
    return run, mirror, worker, browser, inventory
def _admit(layout, *, ports=None, egress=True) -> PlaywrightAdmissionResult:
    _, mirror, _, browser, inventory = layout
    observed = ports or tuple(
        LoopbackPortObservation("127.0.0.1", port) for port in inventory.required_loopback_ports
    )
    return admit_playwright_scenarios(
        inventory,
        PlaywrightPreflightObservation(
            str(mirror / "apps/ui/dist"), True, True,
            str(mirror / "engine/server.py"), True, True,
            str(browser), True, True, True, observed, True, egress, True,
        ),
    )
def _plan(layout, admission, *, scenario_id=None, action="success", artifacts="none", timeout_ms=250):
    run, mirror, worker, browser, inventory = layout
    selected = scenario_id or next(x.scenario_id for x in inventory.scenarios if x.title == "local shell α")
    def command(role: str, behavior: str, output: str) -> E2ECommand:
        argv = (sys.executable, str(worker), role, behavior, output, str(run / f"owned-{role}.started"))
        return E2ECommand(ExactArgumentVector(argv), str(mirror if role == "engine.server" else mirror / "apps/ui"))
    return E2EOrchestrationPlan(
        admission, selected, "local shell α", run, mirror,
        command("preview", "hold", "--production"),
        command("engine.server", "hold", "--production"),
        command("browser", action, artifacts), str(browser), timeout_ms,
    )
def _wait_for(path: Path, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 5.0
    while not path.is_file():
        assert process.poll() is None, f"fixture exited with {process.returncode}"
        assert time.monotonic() < deadline, f"fixture readiness timed out: {path}"
        Event().wait(0.005)
def test_real_occupied_port_blocks_launch_and_preserves_listener(tmp_path: Path) -> None:
    """A real occupied loopback port blocks before launch and its listener survives."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        layout = _fixture(tmp_path, ports=(port,))
        ports = (LoopbackPortObservation("127.0.0.1", port, os.getpid(), False),)
        admission = _admit(layout, ports=ports)
        controller = _Controller()
        with pytest.raises(ValueError, match="not admitted"):
            orchestrate_owned_e2e(_plan(layout, admission), safe_parent_environment=os.environ, controller=controller)
        local = next(x for x in admission.partition.decisions if x.scenario.scenario_id.endswith("local shell α"))
        assert controller.started == []
        assert local.disposition is E2EDisposition.ENVIRONMENT_BLOCKED
        assert local.unavailable_prerequisites == (
            f"free loopback port {port} (pre-existing listener {os.getpid()})",
        )
        with socket.create_connection(("127.0.0.1", port), timeout=1.0) as client:
            accepted, _ = listener.accept()
            accepted.close()
            assert client.getpeername()[1] == port
def test_provider_exclusion_and_empty_inventory_have_exact_zero_failure_counts(tmp_path: Path) -> None:
    """Provider and empty inventories never become executions or local failures."""
    layout = _fixture(tmp_path / "provider")
    admission = _admit(layout)
    provider_id = next(x.scenario_id for x in layout[4].scenarios if x.title == "provider answer β")
    provider = next(x for x in admission.partition.decisions if x.scenario.scenario_id == provider_id)
    projected = E2EPartition(tuple(
        replace(x, scenario=replace(x.scenario, observed_failure=True)) if x is provider else x
        for x in admission.partition.decisions
    ))
    assert provider.disposition is E2EDisposition.EXTERNAL_PROVIDER_DEPENDENT
    assert len(admission.partition.decisions) == 2
    assert len(admission.partition.execution_scenarios) == 1
    assert projected.local_product_failures == ()
    controller = _Controller()
    with pytest.raises(ValueError, match="not admitted"):
        orchestrate_owned_e2e(
            _plan(layout, admission, scenario_id=provider_id),
            safe_parent_environment=os.environ, controller=controller,
        )
    assert controller.started == []
    empty = _fixture(tmp_path / "empty", scenarios=False)
    empty_admission = _admit(empty)
    assert empty[4].scenarios == ()
    assert empty_admission.partition.decisions == ()
    assert empty_admission.partition.execution_scenarios == ()
    assert empty_admission.partition.local_product_failures == ()
    assert (empty_admission.launch_admitted, empty_admission.may_invoke_repository_harness_cleanup) == (False, False)
@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("cwd", "working directory escapes"),
        ("browser", "must be a file in the mirror"),
        ("symlink", "mirror root must not be a symbolic link"),
        ("missing", "not admitted"),
        ("network", "lacks loopback-only network admission"),
        ("dev", "development-server mode is prohibited"),
    ),
)
def test_adversarial_plan_is_refused_before_process_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, message: str
) -> None:
    """Escapes, symlink, outside browser, unknown ID, egress, and dev mode fail closed."""
    layout = _fixture(tmp_path)
    admission = _admit(layout)
    plan = _plan(layout, admission)
    if case == "cwd":
        outside = layout[0] / "outside cwd ü"
        outside.mkdir()
        plan = replace(plan, frontend=replace(plan.frontend, cwd=str(outside)))
    elif case == "browser":
        plan = replace(plan, configured_browser_executable_path=str(_write(layout[0], "outside Ω.exe", "x")))
    elif case == "symlink":
        linked = layout[0] / "linked mirror Ω"
        try:
            linked.symlink_to(layout[1], target_is_directory=True)
        except OSError as error:
            assert getattr(error, "winerror", None) == 1314
            made = subprocess.run(
                ("cmd.exe", "/d", "/c", "mklink", "/J", str(linked), str(layout[1])),
                capture_output=True, check=False,
            )
            assert made.returncode == 0, made.stderr.decode(errors="replace")
            original_is_symlink = Path.is_symlink
            monkeypatch.setattr(
                Path, "is_symlink", lambda self: self == linked or original_is_symlink(self)
            )
        plan = replace(plan, mirror_root=linked)
    elif case == "missing":
        plan = replace(plan, scenario_id="e2e:does-not-exist.spec.ts:1:missing")
    elif case == "network":
        local_id = plan.scenario_id
        decisions = tuple(
            replace(x, scenario=replace(x.scenario, network_policy=NetworkPolicy(NetworkMode.NONE)))
            if x.scenario.scenario_id == local_id else x
            for x in admission.partition.decisions
        )
        plan = replace(plan, admission=replace(admission, partition=E2EPartition(decisions), launch_admitted=True))
    else:
        plan = replace(plan, frontend=E2ECommand(ExactArgumentVector(("pnpm.cmd", "run", "dev")), plan.frontend.cwd))
    controller = _Controller()
    with pytest.raises(ValueError, match=message):
        orchestrate_owned_e2e(plan, safe_parent_environment=os.environ, controller=controller)
    assert controller.started == []
    assert tuple(layout[0].glob("owned-*.started")) == ()
@pytest.mark.parametrize(
    ("action", "artifacts", "abort", "timeout_ms", "termination", "exit_code", "cleanup", "expected"),
    (
        ("success", "both", False, 2000, "exited", 0, CleanupMode.SUCCESS,
         (("screenshot", False, "shot ü.png"), ("trace", False, "trace Ω.zip"))),
        ("failure", "screenshot", False, 2000, "exited", 7, CleanupMode.FAILURE,
         (("screenshot", False, "shot ü.png"), ("trace", True, None))),
        ("hold", "none", False, 40, "timed_out", None, CleanupMode.TIMEOUT,
         (("screenshot", True, None), ("trace", True, None))),
        ("hold", "none", True, 40, "cancelled", None, CleanupMode.ABORT,
         (("screenshot", True, None), ("trace", True, None))),
    ),
)
def test_real_cleanup_and_artifacts_cover_every_termination_path(
    tmp_path: Path, action, artifacts, abort, timeout_ms, termination, exit_code, cleanup, expected
) -> None:
    """Owned processes die on success/failure/timeout/abort while a sentinel survives."""
    layout = _fixture(tmp_path)
    sentinel_ready = layout[0] / "sentinel.ready"
    sentinel = subprocess.Popen(
        (sys.executable, str(layout[2]), "sentinel", "hold", "none", str(sentinel_ready)),
        cwd=layout[1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for(sentinel_ready, sentinel)
        admission = _admit(layout)
        controller = _Controller(abort=abort)
        plan = _plan(layout, admission, action=action, artifacts=artifacts, timeout_ms=timeout_ms)
        result = orchestrate_owned_e2e(plan, safe_parent_environment=os.environ, controller=controller)
        assert layout[4].frontend_startup_is_production is True
        assert layout[4].engine_startup_is_production is True
        assert plan.frontend.exact_argv.values[2:5] == ("preview", "hold", "--production")
        assert plan.engine.exact_argv.values[2:5] == ("engine.server", "hold", "--production")
        assert result.termination.value == termination
        assert result.exit_code == exit_code
        assert controller.wait_timeout_ms == timeout_ms
        assert controller.cleanup_mode is cleanup
        assert [x.role for x in controller.started] == [
            E2EProcessRole.FRONTEND, E2EProcessRole.ENGINE, E2EProcessRole.BROWSER,
        ]
        owned_pids = {x.pid for x in result.process_ownership.processes}
        assert {x.pid for x in controller.started}.issubset(owned_pids)
        assert result.process_ownership.cleanup_completed is True
        assert all(process.poll() is not None for process in controller.processes)
        assert sentinel.poll() is None
        assert sentinel.pid not in {x.pid for x in result.process_ownership.processes}
        observed = tuple(
            (x.kind, x.absent, None if x.path is None else Path(x.path).name)
            for x in result.artifacts
        )
        assert observed == expected
        if action == "failure":
            assert "browser_stdout: browser:failure:screenshot" in result.failure_output
        elif action == "success":
            assert result.failure_output == ()
    finally:
        sentinel.terminate()
        try:
            sentinel.wait(timeout=5)
        except subprocess.TimeoutExpired:
            sentinel.kill()
            sentinel.wait(timeout=5)
