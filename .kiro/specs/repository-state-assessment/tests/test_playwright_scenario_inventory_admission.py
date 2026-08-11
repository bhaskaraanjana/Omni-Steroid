"""Task 5.3 tests for Playwright inventory and fail-closed preflight admission.

Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.9, 4.10.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from assessor import E2EDisposition
from assessor.playwright_preflight_admission import (
    LoopbackPortObservation,
    PlaywrightPreflightObservation,
    admit_playwright_scenarios,
)
from assessor.playwright_scenario_inventory import inventory_playwright_scenarios


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _playwright_fixture(root: Path) -> None:
    _write(
        root,
        "apps/ui/e2e/playwright.config.ts",
        'projects: [\n  { name: "e2e", testMatch: /.*\\.spec\\.ts/ },\n'
        '  { name: "media", testMatch: /.*\\.media\\.ts/ },\n],\n'
        'webServer: { command: "npm run build && npm run preview -- --host 127.0.0.1" },\n',
    )
    _write(
        root,
        "apps/ui/e2e/specs/local.spec.ts",
        'test("local shell", async ({ page }) => { await page.goto("/"); });\n'
        'test("provider answer", async ({ page }) => {\n'
        '  await page.keyboard.press("Enter");\n'
        '  await page.getByRole("article", { name: "Answer" }).waitFor();\n});\n'
        'test.skip("disabled by source", async () => {});\n'
        'test("downloads model", async ({ page }) => {\n'
        '  await page.getByRole("button", { name: "Retry download" }).click();\n});\n',
    )
    _write(
        root,
        "apps/ui/e2e/specs/showcase.media.ts",
        'test("records showcase", async ({ page }) => { await page.goto("/"); });\n',
    )
    _write(
        root,
        "apps/ui/e2e/harness/e2e-env.ts",
        "export const PREVIEW_PORT = 4173;\nexport const ENGINE_PORT = 8765;\n",
    )
    _write(
        root,
        "apps/ui/e2e/harness/engine-process.ts",
        'spawn(VENV_PYTHON, ["-m", "engine.server"]);\n'
        'function stopEngine() { killPort(8765); }\n',
    )


def _passing_preflight(**changes: object) -> PlaywrightPreflightObservation:
    observation = PlaywrightPreflightObservation(
        production_frontend_path="C:/assessment/mirror/apps/ui/dist",
        production_frontend_available=True,
        frontend_startup_is_production=True,
        production_engine_path="C:/assessment/mirror/engine/server.py",
        production_engine_available=True,
        engine_startup_is_production=True,
        browser_executable_path="C:/assessment/browsers/chromium.exe",
        browser_available=True,
        local_test_data_available=True,
        local_services_available=True,
        loopback_ports=(
            LoopbackPortObservation("127.0.0.1", 4173),
            LoopbackPortObservation("127.0.0.1", 8765),
        ),
        write_containment_established=True,
        non_loopback_denial_enforceable=True,
        unsafe_harness_cleanup_disabled=True,
    )
    return replace(observation, **changes)


def test_inventory_parses_every_scenario_and_static_exclusion(tmp_path: Path) -> None:
    _playwright_fixture(tmp_path)

    inventory = inventory_playwright_scenarios(tmp_path, selected_projects=("e2e",))
    by_title = {scenario.title: scenario for scenario in inventory.scenarios}

    assert set(by_title) == {
        "local shell",
        "provider answer",
        "disabled by source",
        "downloads model",
        "records showcase",
    }
    assert by_title["local shell"].included_by_configuration is True
    assert by_title["provider answer"].requires_live_external_provider is True
    assert by_title["disabled by source"].included_by_configuration is False
    assert by_title["downloads model"].included_by_configuration is False
    assert by_title["records showcase"].included_by_configuration is False
    assert inventory.frontend_startup_is_production is True
    assert inventory.engine_startup_is_production is True
    assert inventory.harness_cleanup_kills_by_port is True
    assert len({scenario.scenario_id for scenario in inventory.scenarios}) == 5


def test_admission_partitions_all_scenarios_before_launch(tmp_path: Path) -> None:
    _playwright_fixture(tmp_path)
    inventory = inventory_playwright_scenarios(tmp_path, selected_projects=("e2e",))

    result = admit_playwright_scenarios(inventory, _passing_preflight())
    dispositions = {
        decision.scenario.scenario_id.split(":")[-1]: decision.disposition
        for decision in result.partition.decisions
    }

    assert dispositions == {
        "local shell": E2EDisposition.EXECUTED,
        "provider answer": E2EDisposition.EXTERNAL_PROVIDER_DEPENDENT,
        "disabled by source": E2EDisposition.CONFIGURATION_EXCLUDED,
        "downloads model": E2EDisposition.CONFIGURATION_EXCLUDED,
        "records showcase": E2EDisposition.CONFIGURATION_EXCLUDED,
    }
    assert result.launch_admitted is True
    assert result.may_invoke_repository_harness_cleanup is False


@pytest.mark.parametrize(
    ("changes", "blocker"),
    [
        ({"production_frontend_available": False}, "production frontend build path"),
        ({"frontend_startup_is_production": False}, "production frontend startup path"),
        ({"production_engine_available": False}, "production Python engine path"),
        ({"engine_startup_is_production": False}, "production Python engine startup path"),
        ({"browser_available": False}, "Playwright-configured browser executable"),
        ({"local_test_data_available": False}, "required local test data"),
        ({"local_services_available": False}, "required local services"),
        ({"write_containment_established": False}, "write containment"),
        ({"non_loopback_denial_enforceable": False}, "enforceable non-loopback denial"),
        ({"unsafe_harness_cleanup_disabled": False}, "ownership-safe harness cleanup"),
    ],
)
def test_each_required_preflight_gate_blocks_launch(
    tmp_path: Path,
    changes: dict[str, object],
    blocker: str,
) -> None:
    _playwright_fixture(tmp_path)
    inventory = inventory_playwright_scenarios(tmp_path, selected_projects=("e2e",))

    result = admit_playwright_scenarios(inventory, _passing_preflight(**changes))
    local = next(
        decision
        for decision in result.partition.decisions
        if decision.scenario.scenario_id.endswith(":local shell")
    )

    assert local.disposition is E2EDisposition.ENVIRONMENT_BLOCKED
    assert blocker in local.unavailable_prerequisites
    assert result.launch_admitted is False


def test_existing_listener_blocks_without_permitting_harness_cleanup(tmp_path: Path) -> None:
    _playwright_fixture(tmp_path)
    inventory = inventory_playwright_scenarios(tmp_path, selected_projects=("e2e",))
    ports = (
        LoopbackPortObservation("127.0.0.1", 4173, listener_pid=7311),
        LoopbackPortObservation("127.0.0.1", 8765),
    )

    result = admit_playwright_scenarios(
        inventory,
        _passing_preflight(loopback_ports=ports),
    )
    local = next(
        decision
        for decision in result.partition.decisions
        if decision.scenario.scenario_id.endswith(":local shell")
    )

    assert local.disposition is E2EDisposition.ENVIRONMENT_BLOCKED
    assert "free loopback port 4173 (pre-existing listener 7311)" in local.unavailable_prerequisites
    assert result.launch_admitted is False
    assert result.may_invoke_repository_harness_cleanup is False
