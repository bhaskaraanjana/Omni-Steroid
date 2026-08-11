"""Discover repository-defined verification paths and their prerequisites.

The planner reads current configuration and test sources, records source hashes,
and never installs dependencies or invents commands from remembered defaults.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .discovery_classification import classify_discovery_outcomes
from .discovery_models import (
    DiscoveredCommand,
    DiscoveredTarget,
    RepositoryDiscoveryReport,
)
from .repository_configuration_parsers import (
    SourceDocument,
    load_document,
    parse_lock_versions,
    parse_make_recipes,
    parse_markdown_commands,
    parse_package_scripts,
    parse_playwright_projects,
    parse_playwright_scenarios,
    parse_tauri_targets,
    parse_workflow_commands,
)
from .tool_resolution import ExecutableLookup, ToolResolver, VersionProbe

def _existing_document(root: Path, relative: str) -> SourceDocument | None:
    """Load one candidate only when it exists as a file."""
    path = root / relative
    return load_document(root, path) if path.is_file() else None


def _tools_for_argv(argv: tuple[str, ...]) -> tuple[str, ...]:
    """Infer directly selected executables, including tools run through uv."""
    if not argv:
        return ()
    tools = [Path(argv[0]).stem]
    if tools[0] == "uv" and "run" in argv:
        index = argv.index("run") + 1
        options_with_values = {"--with", "--python", "--project", "--directory"}
        while index < len(argv):
            token = argv[index]
            if token in options_with_values:
                index += 2
            elif token.startswith("-"):
                index += 1
            else:
                tools.append(Path(token).stem)
                break
    return tuple(dict.fromkeys(tools))


def _script_tools(command: str) -> tuple[str, ...]:
    """Extract executable names from each package-script command segment."""
    tools: list[str] = []
    for segment in re.split(r"\s*(?:&&|\|\|)\s*", command):
        token = segment.strip().split(maxsplit=1)[0] if segment.strip() else ""
        if token and "=" not in token:
            tools.append(Path(token).stem)
    return tuple(dict.fromkeys(tools))


def _add_command(
    commands: list[DiscoveredCommand],
    check_id: str,
    argv: tuple[str, ...],
    cwd: str,
    sources: tuple,
    extra_tools: tuple[str, ...] = (),
) -> None:
    """Append a command or merge corroborating sources for the same argv."""
    if not argv or not sources:
        return
    tools = tuple(dict.fromkeys((*_tools_for_argv(argv), *extra_tools)))
    for index, existing in enumerate(commands):
        if existing.check_id != check_id:
            continue
        if existing.argv == argv and existing.cwd == cwd:
            combined_sources = tuple(dict.fromkeys((*existing.sources, *sources)))
            combined_tools = tuple(dict.fromkeys((*existing.required_tools, *tools)))
            commands[index] = DiscoveredCommand(check_id, argv, cwd, combined_sources, combined_tools)
        return
    commands.append(DiscoveredCommand(check_id, argv, cwd, sources, tools))


def _discover_commands(
    root: Path,
    documents: dict[str, SourceDocument],
) -> tuple[DiscoveredCommand, ...]:
    """Build semantic checks from parsed current declarations and manifests."""
    commands: list[DiscoveredCommand] = []
    make = documents.get("Makefile")
    if make:
        recipes = parse_make_recipes(make)
        for target, check_id in {
            "lint": "python-lint",
            "typecheck": "python-types",
            "test": "python-tests",
        }.items():
            if target in recipes:
                argv, source = recipes[target]
                _add_command(commands, check_id, argv, ".", (source,))

    package = documents.get("apps/ui/package.json")
    scripts = parse_package_scripts(package) if package else {}
    for script, check_id in {
        "typecheck": "typescript-types",
        "test": "typescript-tests",
        "build": "frontend-build",
        "coverage": "typescript-coverage",
    }.items():
        if script in scripts:
            command, source = scripts[script]
            _add_command(
                commands, check_id, ("pnpm", "run", script), "apps/ui", (source,),
                _script_tools(command),
            )

    cargo = documents.get("apps/ui/src-tauri/Cargo.toml")
    if cargo:
        rust_sources = [cargo.source(1)]
        cargo_lock = documents.get("apps/ui/src-tauri/Cargo.lock")
        suffix = ("--locked",) if cargo_lock else ()
        if cargo_lock:
            rust_sources.append(cargo_lock.source(1))
        rust_test_sources = []
        for path, document in documents.items():
            if path.startswith("apps/ui/src-tauri/tests/") and "#[test]" in document.text:
                line = next(number for number, text in enumerate(document.lines, 1) if "#[test]" in text)
                rust_test_sources.append(document.source(line))
        _add_command(
            commands, "rust-check", ("cargo", "check", *suffix),
            "apps/ui/src-tauri", tuple(rust_sources), ("rustc",),
        )
        if rust_test_sources or "#[test]" in cargo.text:
            _add_command(
                commands, "rust-tests", ("cargo", "test", *suffix),
                "apps/ui/src-tauri", tuple((*rust_sources, *rust_test_sources)),
                ("rustc",),
            )

    declaration_commands: list[tuple[tuple[str, ...], object]] = []
    for path, document in documents.items():
        if path.startswith(".github/workflows/"):
            declaration_commands.extend(parse_workflow_commands(document))
        elif path.endswith("README.md") and (path.startswith("packaging/") or path == "apps/ui/README.md"):
            declaration_commands.extend(parse_markdown_commands(document))

    for argv, source in declaration_commands:
        lowered = tuple(token.lower() for token in argv)
        joined = " ".join(lowered)
        if "ruff check" in joined:
            _add_command(commands, "python-lint", argv, ".", (source,))
        if "mypy" in lowered:
            _add_command(commands, "python-types", argv, ".", (source,))
        if "pytest" in lowered and not any(token.startswith("--cov") for token in lowered):
            _add_command(commands, "python-tests", argv, ".", (source,))
        if "pnpm run typecheck" in joined:
            _add_command(commands, "typescript-types", argv, "apps/ui", (source,))
        if "pnpm run test" in joined:
            _add_command(commands, "typescript-tests", argv, "apps/ui", (source,))
        if any("pyinstaller" in token for token in lowered):
            _add_command(commands, "engine-build", argv, ".", (source,))
        if "tauri" in joined and "build" in joined:
            desktop_tools = ("pnpm",)
            if "tauri" in scripts:
                desktop_tools = (*desktop_tools, *_script_tools(scripts["tauri"][0]))
            _add_command(
                commands, "desktop-build", argv, "apps/ui", (source,), desktop_tools,
            )
        if any(token == "coverage" or token.startswith("--cov") for token in lowered):
            _add_command(commands, "python-coverage", argv, ".", (source,))

    playwright = documents.get("apps/ui/e2e/playwright.config.ts")
    if playwright:
        for project, _test_match in parse_playwright_projects(playwright):
            line = next(
                (number for number, text in enumerate(playwright.lines, 1) if f'name: "{project}"' in text or f"name: '{project}'" in text),
                1,
            )
            _add_command(
                commands,
                f"local-e2e-{project}",
                ("pnpm", "exec", "playwright", "test", "--config", "e2e/playwright.config.ts", f"--project={project}"),
                "apps/ui",
                (playwright.source(line),),
                ("playwright",),
            )
    return tuple(commands)


def _collect_documents(root: Path) -> dict[str, SourceDocument]:
    """Read all configuration classes required by task 4.4."""
    relative_paths = {
        "Makefile",
        "pyproject.toml",
        ".coveragerc",
        "uv.lock",
        "apps/ui/package.json",
        "apps/ui/pnpm-lock.yaml",
        "apps/ui/vite.config.ts",
        "apps/ui/e2e/playwright.config.ts",
        "apps/ui/src-tauri/Cargo.toml",
        "apps/ui/src-tauri/Cargo.lock",
        "apps/ui/src-tauri/tauri.conf.json",
        "apps/ui/README.md",
        "packaging/README.md",
    }
    for pattern in (
        ".github/workflows/*.*ml",
        "packaging/*.spec",
        "apps/ui/e2e/specs/*.ts",
        "apps/ui/src-tauri/tests/*.rs",
    ):
        relative_paths.update(path.relative_to(root).as_posix() for path in root.glob(pattern) if path.is_file())
    documents: dict[str, SourceDocument] = {}
    for relative in sorted(relative_paths):
        document = _existing_document(root, relative)
        if document:
            documents[relative] = document
    return documents


def _all_search_paths(root: Path, documents: dict[str, SourceDocument]) -> tuple[str, ...]:
    """Enumerate configuration and test sources included in exhaustive search."""
    paths = set(documents)
    for pattern in (
        "tests/**/*.py",
        "apps/ui/src/**/*.test.ts",
        "apps/ui/src/**/*.test.tsx",
        "apps/ui/src-tauri/src/**/*.rs",
    ):
        paths.update(path.relative_to(root).as_posix() for path in root.glob(pattern) if path.is_file())
    return tuple(sorted(paths))


def discover_repository(
    repository_root: Path,
    *,
    host_platform: str | None = None,
    resolve_tools: bool = True,
    search_complete: bool = True,
    executable_lookup: ExecutableLookup | None = None,
    version_probe: VersionProbe | None = None,
) -> RepositoryDiscoveryReport:
    """Discover current verification paths without installing or downloading."""
    root = repository_root.resolve()
    documents = _collect_documents(root)
    commands = _discover_commands(root, documents)
    playwright = documents.get("apps/ui/e2e/playwright.config.ts")
    projects = parse_playwright_projects(playwright) if playwright else ()
    scenarios = tuple(
        scenario
        for path, document in documents.items()
        if path.startswith("apps/ui/e2e/specs/")
        for scenario in parse_playwright_scenarios(document, projects)
    )

    tauri = documents.get("apps/ui/src-tauri/tauri.conf.json")
    platform_name = host_platform or sys.platform
    targets = tuple(
        DiscoveredTarget(name, supported, source)
        for name, supported, source in (parse_tauri_targets(tauri, platform_name) if tauri else ())
    )
    locked_versions = tuple(
        locked
        for path, document in documents.items()
        if path.endswith(("uv.lock", "pnpm-lock.yaml", "Cargo.lock"))
        for locked in parse_lock_versions(document)
    )

    tool_names = tuple(tool for command in commands for tool in command.required_tools)
    resolutions = ()
    if resolve_tools:
        resolutions = ToolResolver(
            root,
            executable_lookup=executable_lookup,
            version_probe=version_probe,
        ).resolve(tool_names)

    search_paths = _all_search_paths(root, documents)
    outcomes = classify_discovery_outcomes(commands, search_paths, search_complete, resolutions)
    return RepositoryDiscoveryReport(
        commands=commands,
        scenarios=scenarios,
        targets=targets,
        locked_versions=locked_versions,
        tool_resolutions=resolutions,
        outcomes=outcomes,
    )
