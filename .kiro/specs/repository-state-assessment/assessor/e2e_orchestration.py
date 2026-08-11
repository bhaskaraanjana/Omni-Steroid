"""Run one admitted Local E2E scenario with owned production processes.

The orchestration is mirror-only, credential-free, and loopback-contained. It starts
exactly production preview, real local engine, and Playwright/browser roles, captures
separate diagnostics, and always delegates cleanup by assessment ownership identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

from .contained_process_environment import build_contained_environment
from .e2e_orchestration_models import E2ECommand as E2ECommand
from .e2e_orchestration_models import (
    E2EOrchestrationPlan,
    E2EOrchestrationResult,
    E2EOutputReferences,
    OwnedE2EController,
)
from .e2e_orchestration_output_capture import (
    allocate_output_paths,
    collect_artifacts,
    configure_e2e_environment,
    read_failure_output,
    relative_ref,
)
from .e2e_orchestration_plan_validation import validate_plan
from .e2e_process_controller import E2EProcessCompletion as E2EProcessCompletion
from .e2e_process_controller import (
    E2EProcessHandle,
    E2EProcessRole,
    SubprocessOwnedE2EController,
)
from .execution_models import TerminationKind
from .process_cleanup import CleanupMode


def orchestrate_owned_e2e(
    plan: E2EOrchestrationPlan,
    *,
    safe_parent_environment: Mapping[str, str],
    controller: OwnedE2EController | None = None,
) -> E2EOrchestrationResult:
    """Run one admitted local scenario and always clean its owned process trees.

    The caller must have established the preflight admission represented by ``plan``.
    Invalid admission or paths fail before process creation. Keyboard interruption is
    captured as a cancelled result after ownership-safe cleanup.
    """
    temporary_root, _mirror_root, browser_executable = validate_plan(plan)
    ownership_token = f"e2e-{uuid4().hex}"
    environment = build_contained_environment(
        temporary_root, ownership_token, safe_parent_environment
    )
    configure_e2e_environment(environment, browser_executable)
    paths = allocate_output_paths(temporary_root, ownership_token)
    active_controller = controller or SubprocessOwnedE2EController()
    handles: list[E2EProcessHandle] = []
    termination = TerminationKind.CRASHED
    exit_code: int | None = None
    cleanup_mode = CleanupMode.FAILURE
    try:
        for role, command in (
            (E2EProcessRole.FRONTEND, plan.frontend),
            (E2EProcessRole.ENGINE, plan.engine),
            (E2EProcessRole.BROWSER, plan.browser),
        ):
            handle = active_controller.start(
                role,
                command,
                environment,
                paths[f"{role.value}_stdout"],
                paths[f"{role.value}_stderr"],
                ownership_token,
            )
            handles.append(handle)
        completion = active_controller.wait(handles[-1], plan.timeout_ms)
        exit_code = completion.exit_code
        if completion.timed_out:
            termination = TerminationKind.TIMED_OUT
            cleanup_mode = CleanupMode.TIMEOUT
        elif exit_code is None:
            termination = TerminationKind.CRASHED
        else:
            termination = TerminationKind.EXITED
            cleanup_mode = CleanupMode.SUCCESS if exit_code == 0 else CleanupMode.FAILURE
    except KeyboardInterrupt:
        termination = TerminationKind.CANCELLED
        cleanup_mode = CleanupMode.ABORT
    finally:
        process_ownership = active_controller.cleanup(
            tuple(handles), ownership_token, cleanup_mode
        )

    outputs = E2EOutputReferences(
        scenario_output_ref=relative_ref(paths["browser_stdout"], temporary_root),
        frontend_output_ref=relative_ref(paths["frontend_stdout"], temporary_root),
        engine_output_ref=relative_ref(paths["engine_stdout"], temporary_root),
        browser_output_ref=relative_ref(paths["browser_stderr"], temporary_root),
    )
    artifacts = collect_artifacts(environment, temporary_root)
    failed = termination is not TerminationKind.EXITED or exit_code != 0
    return E2EOrchestrationResult(
        scenario_id=plan.scenario_id,
        scenario_name=plan.scenario_name,
        termination=termination,
        exit_code=exit_code,
        outputs=outputs,
        failure_output=read_failure_output(paths) if failed else (),
        artifacts=artifacts,
        process_ownership=process_ownership,
    )
