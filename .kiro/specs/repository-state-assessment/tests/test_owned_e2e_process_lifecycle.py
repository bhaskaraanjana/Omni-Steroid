"""Task 5.4 tests for owned Local E2E orchestration and failure capture.

Validates: Requirements 4.2, 4.3, 4.6, 4.7, 4.8, 7.1, 7.2.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from assessor.e2e_orchestration import (
    E2ECommand,
    E2EOrchestrationPlan,
    E2EProcessCompletion,
    E2EProcessHandle,
    E2EProcessRole,
    orchestrate_owned_e2e,
)
from assessor.e2e_partition import (
    E2EDisposition,
    E2EPartition,
    E2EScenario,
    E2EScenarioDecision,
)
from assessor.execution_models import CommandSource
from assessor.model_types import (
    ExactArgumentVector,
    NetworkMode,
    NetworkPolicy,
    ProcessOwnership,
    SourceLocation,
)
from assessor.playwright_preflight_admission import PlaywrightAdmissionResult
from assessor.playwright_scenario_inventory import (
    PlaywrightScenarioInventory,
    PlaywrightScenarioMetadata,
)
from assessor.process_cleanup import CleanupMode

class _FakeOwnedController:
    def __init__(self, *, exit_code: int = 1, abort: bool = False) -> None:
        self.exit_code = exit_code
        self.abort = abort
        self.starts: list[tuple[E2EProcessRole, E2ECommand, dict[str, str], Path, Path]] = []
        self.cleaned: tuple[E2EProcessHandle, ...] = ()
        self.cleanup_mode: CleanupMode | None = None
        self.preexisting_processes = {47}

    def start(
        self,
        role: E2EProcessRole,
        command: E2ECommand,
        environment: dict[str, str],
        stdout_path: Path,
        stderr_path: Path,
        ownership_token: str,
    ) -> E2EProcessHandle:
        del ownership_token
        stdout_path.write_text(f"{role.value} scenario output\n", encoding="utf-8")
        stderr_path.write_text(f"{role.value} diagnostic\n", encoding="utf-8")
        self.starts.append((role, command, dict(environment), stdout_path, stderr_path))
        return E2EProcessHandle(role=role, pid=100 + len(self.starts))

    def wait(
        self, handle: E2EProcessHandle, timeout_ms: int
    ) -> E2EProcessCompletion:
        assert handle.role is E2EProcessRole.BROWSER
        assert timeout_ms == 5_000
        environment = self.starts[-1][2]
        Path(environment["OMNI_E2E_SCREENSHOT_DIR"], "failure.png").write_bytes(b"png")
        if self.abort:
            raise KeyboardInterrupt
        return E2EProcessCompletion(exit_code=self.exit_code)

    def cleanup(
        self,
        handles: tuple[E2EProcessHandle, ...],
        ownership_token: str,
        mode: CleanupMode,
    ) -> ProcessOwnership:
        self.cleaned = handles
        self.cleanup_mode = mode
        return ProcessOwnership(
            ownership_token=ownership_token,
            mechanism="fixture-owned-handles",
            cleanup_completed=True,
        )

def _admission(scenario_id: str) -> PlaywrightAdmissionResult:
    source = CommandSource(SourceLocation("apps/ui/e2e/local.spec.ts", 1, 1), "a" * 64)
    metadata = PlaywrightScenarioMetadata(
        scenario_id=scenario_id,
        project="e2e",
        title="local shell",
        source=source,
        requires_live_external_provider=False,
        included_by_configuration=True,
    )
    scenario = E2EScenario(
        scenario_id=scenario_id,
        requires_live_external_provider=False,
        included_by_configuration=True,
        prerequisites=(),
        network_policy=NetworkPolicy(NetworkMode.LOOPBACK_ONLY),
    )
    return PlaywrightAdmissionResult(
        inventory=PlaywrightScenarioInventory(
            scenarios=(metadata,),
            frontend_startup_is_production=True,
            engine_startup_is_production=True,
            harness_cleanup_kills_by_port=False,
            required_loopback_ports=(4173, 8765),
        ),
        partition=E2EPartition((E2EScenarioDecision(scenario, E2EDisposition.EXECUTED),)),
        launch_admitted=True,
        may_invoke_repository_harness_cleanup=False,
    )

def _plan(tmp_path: Path) -> E2EOrchestrationPlan:
    run_root = tmp_path / "run"
    mirror = run_root / "mirror"
    ui = mirror / "apps" / "ui"
    engine = mirror / "engine"
    ui.mkdir(parents=True)
    engine.mkdir(parents=True)
    browser = mirror / "browsers" / "chromium.exe"
    browser.parent.mkdir()
    browser.write_bytes(b"fixture browser")
    scenario_id = "e2e:apps/ui/e2e/local.spec.ts:1:local shell"
    return E2EOrchestrationPlan(
        admission=_admission(scenario_id),
        scenario_id=scenario_id,
        scenario_name="local shell",
        temporary_root=run_root,
        mirror_root=mirror,
        frontend=E2ECommand(
            ExactArgumentVector((sys.executable, "fixture-preview.py", "--production")),
            str(ui),
        ),
        engine=E2ECommand(
            ExactArgumentVector((sys.executable, "-m", "engine.server")),
            str(mirror),
        ),
        browser=E2ECommand(
            ExactArgumentVector((sys.executable, "fixture-playwright.py", "--project=e2e")),
            str(ui),
        ),
        configured_browser_executable_path=str(browser),
        timeout_ms=5_000,
    )

def test_orchestrates_only_production_components_with_isolated_paths_and_failure_capture(
    tmp_path: Path,
) -> None:
    controller = _FakeOwnedController(exit_code=1)
    plan = _plan(tmp_path)

    result = orchestrate_owned_e2e(
        plan,
        safe_parent_environment={
            "PATH": os.environ.get("PATH", ""),
            "GEMINI_API_KEY": "must-not-be-inherited",
            "OMNI_E2E_REUSE_ENGINE": "1",
        },
        controller=controller,
    )

    assert [item[0] for item in controller.starts] == [
        E2EProcessRole.FRONTEND,
        E2EProcessRole.ENGINE,
        E2EProcessRole.BROWSER,
    ]
    assert [item[1] for item in controller.starts] == [
        plan.frontend,
        plan.engine,
        plan.browser,
    ]
    environment = controller.starts[0][2]
    assert "GEMINI_API_KEY" not in environment
    assert "OMNI_E2E_REUSE_ENGINE" not in environment
    assert environment["OMNI_E2E_ALLOW_NO_KEYS"] == "1"
    assert not Path(environment["OMNI_ENV_FILE"]).exists()
    for name in (
        "OMNI_DB_PATH",
        "OMNI_MODELS_DIR",
        "OMNI_E2E_REPORT_DIR",
        "OMNI_E2E_SCREENSHOT_DIR",
        "OMNI_E2E_TRACE_DIR",
        "PLAYWRIGHT_OUTPUT_DIR",
    ):
        assert Path(environment[name]).resolve().is_relative_to(plan.temporary_root.resolve())
    assert environment["OMNI_E2E_BROWSER_EXECUTABLE"] == plan.configured_browser_executable_path

    assert result.failed is True
    assert result.scenario_name == "local shell"
    assert result.outputs.scenario_output_ref.endswith("browser.stdout")
    assert result.outputs.frontend_output_ref.endswith("frontend.stdout")
    assert result.outputs.engine_output_ref.endswith("engine.stdout")
    assert result.outputs.browser_output_ref.endswith("browser.stderr")
    assert "browser scenario output" in "\n".join(result.failure_output)
    assert [(artifact.kind, artifact.absent) for artifact in result.artifacts] == [
        ("screenshot", False),
        ("trace", True),
    ]
    screenshot = next(item for item in result.artifacts if item.kind == "screenshot")
    assert screenshot.path is not None
    assert (plan.temporary_root / screenshot.path).is_file()
    assert result.process_ownership.cleanup_completed is True
    assert {handle.pid for handle in controller.cleaned} == {101, 102, 103}
    assert controller.preexisting_processes == {47}
    assert controller.cleanup_mode is CleanupMode.FAILURE

def test_abort_still_cleans_only_started_assessment_processes_and_marks_artifacts_absent(
    tmp_path: Path,
) -> None:
    controller = _FakeOwnedController(abort=True)
    plan = _plan(tmp_path)

    result = orchestrate_owned_e2e(
        plan,
        safe_parent_environment={"PATH": os.environ.get("PATH", "")},
        controller=controller,
    )

    assert result.termination.value == "cancelled"
    assert controller.cleanup_mode is CleanupMode.ABORT
    assert [handle.role for handle in controller.cleaned] == [
        E2EProcessRole.FRONTEND,
        E2EProcessRole.ENGINE,
        E2EProcessRole.BROWSER,
    ]
    assert controller.preexisting_processes == {47}
    assert result.process_ownership.cleanup_completed is True
    assert any(item.kind == "trace" and item.absent for item in result.artifacts)

def test_successful_completion_cleans_owned_processes_without_failure_output(
    tmp_path: Path,
) -> None:
    controller = _FakeOwnedController(exit_code=0)
    plan = _plan(tmp_path)

    result = orchestrate_owned_e2e(
        plan,
        safe_parent_environment={"PATH": os.environ.get("PATH", "")},
        controller=controller,
    )

    assert result.failed is False
    assert result.termination.value == "exited"
    assert result.exit_code == 0
    assert result.failure_output == ()
    assert controller.cleanup_mode is CleanupMode.SUCCESS
    assert [handle.role for handle in controller.cleaned] == [
        E2EProcessRole.FRONTEND,
        E2EProcessRole.ENGINE,
        E2EProcessRole.BROWSER,
    ]
    assert controller.preexisting_processes == {47}
