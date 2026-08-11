"""Task 11.5 tests for the reachable, fail-closed Local E2E phase."""

from __future__ import annotations

import json
from pathlib import Path

from assessor.assessment_phase_gates import AssessmentPhase, parse_phase
from assessor.local_e2e_phase import execute_local_e2e


def _write(root: Path, relative: str, text: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _fixture(root: Path) -> None:
    _write(
        root,
        "apps/ui/e2e/playwright.config.ts",
        'projects: [{ name: "e2e", testMatch: /.*\\.spec\\.ts/ }],\n'
        'webServer: { command: "npm run build && npm run preview" },\n',
    )
    _write(
        root,
        "apps/ui/e2e/specs/local.spec.ts",
        'test("local shell", async ({ page }) => { await page.goto("/"); });\n'
        'test("provider answer", async ({ page }) => { await page.keyboard.press("Enter"); '
        'await page.getByRole("article", { name: "Answer" }).waitFor(); });\n'
        'test.skip("disabled", async () => {});\n',
    )
    _write(
        root,
        "apps/ui/e2e/harness/e2e-env.ts",
        "export const PREVIEW_PORT = 4173;\nexport const ENGINE_PORT = 8765;\n",
    )
    _write(
        root,
        "apps/ui/e2e/harness/engine-process.ts",
        'spawn(PYTHON, ["-m", "engine.server"]);\nfunction stop() { killPort(8765); }\n',
    )
    _write(root, "engine/server.py", "# fixture engine\n")
    _write(root, "apps/ui/e2e/harness/seed_engine.py", "# fixture seed\n")
    _write(root, "apps/ui/e2e/fixtures/vault/note.md", "fixture\n")
    (root / "migrations").mkdir()


def test_local_e2e_is_an_explicit_cli_phase() -> None:
    assert parse_phase("local-e2e") is AssessmentPhase.LOCAL_E2E


def test_blocked_phase_records_every_preflight_and_explicit_artifact_absence(
    tmp_path: Path,
) -> None:
    mirror = tmp_path / "mirror"
    temporary = tmp_path / "temporary"
    output = tmp_path / "output"
    mirror.mkdir()
    temporary.mkdir()
    # A prior mirror-execution phase owns this audit directory; Local E2E must
    # establish an independent audit root rather than treating it as a failure.
    (temporary / "write-audit").mkdir()
    output.mkdir()
    _fixture(mirror)

    result = execute_local_e2e(
        mirror,
        temporary,
        output,
        ownership_token="assessment-fixture-token",
    )

    payload = json.loads((output / "local-e2e.json").read_text(encoding="utf-8"))
    assert result.artifact_refs == (str(output / "local-e2e.json"),)
    assert len(payload["scenarios"]) == 3
    assert {item["disposition"] for item in payload["scenarios"]} == {
        "environment_blocked",
        "external_provider_dependent",
        "configuration_excluded",
    }
    assert all(item["outputs"]["screenshot"]["state"] == "absent" for item in payload["scenarios"])
    assert all(item["outputs"]["trace"]["state"] == "absent" for item in payload["scenarios"])
    by_name = {item["name"]: item for item in payload["preflights"]}
    assert by_name["production frontend build"]["status"] == "blocked"
    assert by_name["real local engine"]["status"] == "passed"
    assert by_name["configured browser"]["status"] == "blocked"
    assert by_name["process ownership"]["status"] == "passed"
    assert by_name["write audit"]["status"] == "passed"
    assert by_name["loopback-only egress"]["status"] == "blocked"
    assert payload["process_cleanup"]["owned_processes_started"] == 0
    assert payload["process_cleanup"]["assessment_owned_processes_surviving"] == 0
