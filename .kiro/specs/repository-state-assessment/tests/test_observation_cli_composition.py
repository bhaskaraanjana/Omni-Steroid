"""Task 11.3 real observation-only CLI composition tests."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from assessor.assessment_cli import main
from assessor.assessment_phase_gates import AssessmentPhase, GateStatus
from assessor.model_types import ZonedTimestamp
from assessor.run_manifest_append_store import AppendOnlyRunManifest

_NOW = ZonedTimestamp(datetime(2026, 7, 31, tzinfo=timezone.utc))


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def _write(root: Path, relative: str, text: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def test_direct_cli_observes_real_fixture_and_stops_before_execution(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "--initial-branch=main")
    _git(source, "config", "user.email", "assessment@example.invalid")
    _git(source, "config", "user.name", "Assessment Fixture")
    _write(source, "README.md", "Omni captures meetings locally.\n")
    _write(source, ".env", "PRIVATE_VALUE=must-not-appear\n")
    _write(source, "Makefile", "lint:\n\tuv run ruff check .\n")
    _write(
        source,
        "apps/ui/e2e/playwright.config.ts",
        'projects: [{ name: "local", testMatch: /.*\\.spec\\.ts/ }],\n',
    )
    _write(
        source,
        "apps/ui/e2e/specs/library.spec.ts",
        'test("opens library", async ({ page }) => {});\n',
    )
    _git(source, "add", "--", ".")
    _git(source, "commit", "-m", "fixture")

    output = source / ".kiro/specs/repository-state-assessment/assessment-output/run-fixture"
    temporary = tmp_path / "temporary-run"
    output.mkdir(parents=True)
    temporary.mkdir()
    manifest = output / "run-manifest.jsonl"
    argv = [
        "run", "--manifest", str(manifest), "--run-id", "run-fixture",
        "--source-root", str(source), "--temporary-root", str(temporary),
        "--output-root", str(output), "--observation-only",
        "--phase-limit", "discovery/admission",
    ]

    assert main(argv) == 2

    state = AppendOnlyRunManifest.open(manifest, clock=lambda: _NOW).state()
    assert state.gate_for(AssessmentPhase.BASELINE) is GateStatus.GREEN
    assert state.gate_for(AssessmentPhase.CLAIMS) is GateStatus.GREEN
    assert state.gate_for(AssessmentPhase.DISCOVERY_ADMISSION) is GateStatus.INCONCLUSIVE
    assert state.gate_for(AssessmentPhase.MIRROR_EXECUTION) is None
    assert state.final_comparison_records[-1].comparison_preserved is True

    summary = json.loads((output / "observation-summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["files_hashed"] >= 5
    assert summary["counts"]["claims_inventoried"] == 1
    assert summary["counts"]["scenarios_found"] == 1
    assert summary["admission"]["loopback_enforcement_established"] is False
    command_omissions = {
        item["operation_id"]: item for item in summary["omissions"]
    }
    assert command_omissions["python-lint"]["dependent_checks"][0]["status"] == (
        "Unverified"
    )
    assert any(
        item["operation_id"] == "mirror-process-execution"
        for item in summary["omissions"]
    )
    assert "must-not-appear" not in json.dumps(summary)
    assert (temporary / "mirror" / "README.md").is_file()


def test_direct_cli_composes_and_reaches_mirror_execution(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "--initial-branch=main")
    _git(source, "config", "user.email", "assessment@example.invalid")
    _git(source, "config", "user.name", "Assessment Fixture")
    _write(source, "README.md", "Contained mirror fixture.\n")
    _write(
        source,
        "Makefile",
        f'test:\n\t"{Path(__import__("sys").executable)}" -c "print(\'1 passed\')"\n',
    )
    _git(source, "add", "--", ".")
    _git(source, "commit", "-m", "fixture")

    output = source / ".kiro/specs/repository-state-assessment/assessment-output/run-mirror"
    temporary = tmp_path / "temporary-run"
    output.mkdir(parents=True)
    temporary.mkdir()
    manifest = output / "run-manifest.jsonl"
    argv = [
        "run", "--manifest", str(manifest), "--run-id", "run-mirror",
        "--source-root", str(source), "--temporary-root", str(temporary),
        "--output-root", str(output), "--phase-limit", "mirror execution",
    ]

    assert main(argv) == 2

    state = AppendOnlyRunManifest.open(manifest, clock=lambda: _NOW).state()
    assert state.gate_for(AssessmentPhase.DISCOVERY_ADMISSION) is GateStatus.GREEN
    assert state.gate_for(AssessmentPhase.MIRROR_EXECUTION) is GateStatus.GREEN
    evidence = json.loads((output / "mirror-execution.json").read_text(encoding="utf-8"))
    python_tests = next(item for item in evidence["checks"] if item["check_id"] == "python-tests")
    assert python_tests["status"] == "passed"
    assert python_tests["test_counts"]["passed"] == 1
    assert python_tests["attempt_count"] == 1
    required_omissions = {"frozen-engine-smoke", "packaging", "hermetic-security"}
    omissions = {item["check_id"]: item for item in evidence["checks"]}
    assert required_omissions <= omissions.keys()
    assert all(omissions[item]["status"] == "not implemented" for item in required_omissions)
    assert state.final_comparison_records[-1].comparison_preserved is True


def test_nonzero_version_probe_cannot_become_a_resolved_version(
    monkeypatch,
) -> None:
    from assessor import observation_support

    failed = subprocess.CompletedProcess(
        args=("broken-tool.exe", "--version"),
        returncode=1,
        stdout="not recognized as an internal command",
        stderr="",
    )
    monkeypatch.setattr(observation_support.subprocess, "run", lambda *args, **kwargs: failed)

    assert observation_support._probe_version("broken-tool.exe") is None
