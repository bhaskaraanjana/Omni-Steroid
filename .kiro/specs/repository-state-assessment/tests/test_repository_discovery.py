"""Task 4.4 tests for configuration-derived repository discovery."""

from __future__ import annotations

import hashlib
from pathlib import Path

from assessor.model_types import AssessmentStatus
from assessor.repository_discovery import discover_repository
from assessor.tool_resolution import ToolResolver


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture_repository(root: Path) -> None:
    _write(
        root,
        "Makefile",
        "lint:\n\tuv run ruff check engine\n"
        "typecheck:\n\tuv run mypy engine\n"
        "test:\n\tuv run pytest -m 'not hardware'\n",
    )
    _write(
        root,
        "pyproject.toml",
        "[project]\nrequires-python = \">=3.11,<3.12\"\n"
        "[tool.mypy]\nstrict = true\n[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\n",
    )
    _write(root, ".coveragerc", "[run]\nbranch = True\n")
    _write(root, "uv.lock", '[[package]]\nname = "ruff"\nversion = "9.8.7"\n')
    _write(
        root,
        "apps/ui/package.json",
        '{"scripts":{"typecheck":"custom-ts-check --strict","test":"custom-vitest once",'
        '"build":"custom-ts-check && custom-vite build","tauri":"custom-tauri"},'
        '"devDependencies":{"custom-vitest":"1.0.0"}}',
    )
    _write(
        root,
        "apps/ui/pnpm-lock.yaml",
        "lockfileVersion: '9.0'\n  custom-vitest:\n    version: 1.2.3\n"
        "  '@playwright/test':\n    version: 1.61.1\n",
    )
    _write(root, "apps/ui/vite.config.ts", 'test: { exclude: ["e2e/**"] }\n')
    _write(
        root,
        "apps/ui/e2e/playwright.config.ts",
        'testDir: "./specs",\nprojects: [\n'
        '  { name: "local", testMatch: /.*\\.spec\\.ts/ },\n'
        '  { name: "media", testMatch: /.*\\.media\\.ts/ },\n],\n',
    )
    _write(
        root,
        "apps/ui/e2e/specs/local.spec.ts",
        'test.describe("library", () => {\n'
        '  test("opens a meeting", async ({ page }) => {});\n'
        '});\n',
    )
    _write(
        root,
        "apps/ui/e2e/specs/showcase.media.ts",
        'test("records product", async ({ page }) => {});\n',
    )
    _write(root, "apps/ui/src-tauri/Cargo.toml", '[package]\nname = "fixture-ui"\n')
    _write(root, "apps/ui/src-tauri/Cargo.lock", "version = 4\n")
    _write(
        root,
        "apps/ui/src-tauri/tauri.conf.json",
        '{"bundle":{"active":true,"targets":["nsis","msi","dmg"]}}',
    )
    _write(
        root,
        "apps/ui/src-tauri/tests/native_roundtrip.rs",
        '#[test]\n#[ignore = "desktop"]\nfn roundtrip() {}\n',
    )
    _write(
        root,
        ".github/workflows/ci.yml",
        "steps:\n  - name: lint\n    run: uv run ruff check engine\n",
    )
    _write(
        root,
        "packaging/README.md",
        "```powershell\n"
        "uv run pyinstaller packaging/fixture.spec --noconfirm\n"
        "cmd /c \"call setup_x64.bat && pnpm tauri build\"\n"
        "```\n",
    )
    _write(root, "packaging/fixture.spec", "# fixture package specification\n")


def test_discovers_commands_scenarios_targets_and_hashed_sources(tmp_path: Path) -> None:
    _fixture_repository(tmp_path)

    report = discover_repository(tmp_path, host_platform="win32", resolve_tools=False)
    commands = {item.check_id: item for item in report.commands}

    assert commands["python-lint"].argv == ("uv", "run", "ruff", "check", "engine")
    assert commands["python-types"].argv[-2:] == ("mypy", "engine")
    assert commands["typescript-types"].argv == (
        "pnpm",
        "run",
        "typecheck",
    )
    assert commands["rust-check"].argv == ("cargo", "check", "--locked")
    assert commands["rust-tests"].argv == ("cargo", "test", "--locked")
    assert commands["local-e2e-local"].argv[-1] == "--project=local"
    assert commands["engine-build"].argv[:3] == ("uv", "run", "pyinstaller")
    assert commands["desktop-build"].argv[0:2] == ("cmd", "/c")
    assert {"cmd", "pnpm", "custom-tauri"} <= set(commands["desktop-build"].required_tools)
    assert {"cargo", "rustc"} <= set(commands["rust-tests"].required_tools)
    assert {source.location.path for source in commands["python-lint"].sources} == {
        "Makefile",
        ".github/workflows/ci.yml",
    }
    assert "apps/ui/src-tauri/tests/native_roundtrip.rs" in {
        source.location.path for source in commands["rust-tests"].sources
    }

    make_source = commands["python-lint"].sources[0]
    assert make_source.location.path == "Makefile"
    assert make_source.location.start_line == 2
    assert make_source.sha256 == hashlib.sha256((tmp_path / "Makefile").read_bytes()).hexdigest()

    assert {(item.project, item.title) for item in report.scenarios} == {
        ("local", "opens a meeting"),
        ("media", "records product"),
    }
    assert {item.name: item.host_supported for item in report.targets} == {
        "nsis": True,
        "msi": True,
        "dmg": False,
    }
    assert ("custom-vitest", "1.2.3") in {
        (item.name, item.version) for item in report.locked_versions
    }


def test_commands_are_derived_from_current_configuration_not_known_defaults(tmp_path: Path) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path,
        "Makefile",
        "lint:\n\tuv run ruff check changed_scope --diff\n"
        "typecheck:\n\tuv run mypy changed_scope\n"
        "test:\n\tuv run pytest changed_tests\n",
    )

    report = discover_repository(tmp_path, resolve_tools=False)
    commands = {item.check_id: item.argv for item in report.commands}

    assert commands["python-lint"][-2:] == ("changed_scope", "--diff")
    assert commands["python-tests"][-1] == "changed_tests"
    assert ("uv", "run", "ruff", "check", ".") not in commands.values()


def test_absent_paths_require_complete_search_and_named_missing_tools_block(
    tmp_path: Path,
) -> None:
    _fixture_repository(tmp_path)
    report = discover_repository(
        tmp_path,
        resolve_tools=True,
        executable_lookup=lambda _name, _paths: None,
        version_probe=lambda _path, _args: None,
    )
    outcomes = {item.check_id: item for item in report.outcomes}

    assert outcomes["python-coverage"].search.complete is True
    assert outcomes["python-coverage"].status is AssessmentStatus.NOT_IMPLEMENTED
    assert outcomes["typescript-coverage"].status is AssessmentStatus.NOT_IMPLEMENTED
    assert outcomes["python-lint"].status is AssessmentStatus.ENVIRONMENT_BLOCKED
    assert "uv" in outcomes["python-lint"].missing_prerequisites

    incomplete = discover_repository(
        tmp_path,
        resolve_tools=False,
        search_complete=False,
    )
    incomplete_outcomes = {item.check_id: item for item in incomplete.outcomes}
    assert incomplete_outcomes["python-coverage"].status is AssessmentStatus.UNVERIFIED


def test_tool_resolution_only_probes_existing_executables_for_versions(tmp_path: Path) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def lookup(name: str, _paths: tuple[Path, ...]) -> str | None:
        return str(tmp_path / f"{name}.exe") if name == "uv" else None

    def probe(path: str, args: tuple[str, ...]) -> str | None:
        calls.append((path, args))
        return "uv 9.7.1"

    result = ToolResolver(tmp_path, executable_lookup=lookup, version_probe=probe).resolve(
        ("uv", "missing-tool")
    )

    by_name = {item.name: item for item in result}
    assert by_name["uv"].available is True
    assert by_name["uv"].version == "uv 9.7.1"
    assert by_name["missing-tool"].available is False
    assert calls == [(str(tmp_path / "uv.exe"), ("--version",))]
    assert all("install" not in arg and "download" not in arg for _, args in calls for arg in args)
