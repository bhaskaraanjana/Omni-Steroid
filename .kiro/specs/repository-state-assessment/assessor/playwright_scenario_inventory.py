"""Static Playwright scenario and production-harness inventory.

The parser reads current repository declarations without executing TypeScript,
launching Playwright, or consulting provider credentials. Every test source is
retained so configuration exclusions remain visible in the final partition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .execution_models import CommandSource
from .repository_configuration_parsers import (
    SourceDocument,
    load_document,
    parse_playwright_projects,
)


@dataclass(frozen=True, slots=True)
class PlaywrightScenarioMetadata:
    """Static configuration and dependency facts for one test declaration."""

    scenario_id: str
    project: str
    title: str
    source: CommandSource
    requires_live_external_provider: bool
    included_by_configuration: bool
    configuration_exclusion_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PlaywrightScenarioInventory:
    """Complete configured scenario and harness inventory before admission."""

    scenarios: tuple[PlaywrightScenarioMetadata, ...]
    frontend_startup_is_production: bool
    engine_startup_is_production: bool
    harness_cleanup_kills_by_port: bool
    required_loopback_ports: tuple[int, ...]


_TEST_PATTERN = re.compile(
    r"(?<![.\w])test(?P<modifier>\.(?:skip|fixme))?\s*\(\s*"
    r"(?P<quote>[\"'`])(?P<title>.*?)(?P=quote)",
)


def _project_for_file(file_name: str, projects: tuple[tuple[str, str], ...]) -> str:
    """Resolve the configured project for the repository's static testMatch forms."""
    for name, expression in projects:
        if ".media." in file_name and "media" in expression:
            return name
        if ".spec." in file_name and "spec" in expression and "media" not in expression:
            return name
    return "unconfigured"


def _balanced_test_body(text: str, declaration_end: int) -> str:
    """Return a test callback block without executing TypeScript configuration."""
    arrow = text.find("=>", declaration_end)
    opening = text.find("{", arrow if arrow >= 0 else declaration_end)
    if opening < 0:
        return ""
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index]
    return text[opening + 1 :]


def _requires_provider(title: str, body: str) -> bool:
    """Recognize current mandatory Ask-synthesis paths, not optional UI display."""
    direct_answer_wait = (
        "keyboard.press" in body
        and 'name: "Answer"' in body
        and ".catch" not in body
    )
    return bool(
        re.search(r"\bask\s*\(\s*page\b", body)
        or ("ask (answered)" in title.casefold() and "keyboard.press" in body)
        or direct_answer_wait
        or '"ask.query"' in body
        or "'ask.query'" in body
    )


def _requires_remote_download(body: str) -> bool:
    """Identify scenarios whose current behavior can leave loopback for downloads."""
    lowered = body.casefold()
    return "retry download" in lowered or "model.download" in lowered


def _scenario_metadata(
    document: SourceDocument,
    projects: tuple[tuple[str, str], ...],
    selected_projects: frozenset[str],
) -> tuple[PlaywrightScenarioMetadata, ...]:
    project = _project_for_file(Path(document.relative_path).name, projects)
    scenarios: list[PlaywrightScenarioMetadata] = []
    for match in _TEST_PATTERN.finditer(document.text):
        title = match.group("title")
        body = _balanced_test_body(document.text, match.end())
        line = document.text.count("\n", 0, match.start()) + 1
        reason: str | None = None
        if project not in selected_projects:
            reason = f"project {project!r} is not selected"
        elif match.group("modifier") is not None:
            reason = f"source declaration uses test{match.group('modifier')}"
        elif _requires_remote_download(body):
            reason = "scenario requires a remote model download under loopback-only policy"
        included = reason is None
        scenario_id = f"{project}:{document.relative_path}:{line}:{title}"
        scenarios.append(
            PlaywrightScenarioMetadata(
                scenario_id=scenario_id,
                project=project,
                title=title,
                source=document.source(line),
                requires_live_external_provider=included and _requires_provider(title, body),
                included_by_configuration=included,
                configuration_exclusion_reason=reason,
            )
        )
    return tuple(scenarios)


def _port_constants(document: SourceDocument | None) -> tuple[int, ...]:
    if document is None:
        return ()
    values = {
        int(match.group(1))
        for match in re.finditer(
            r"(?:ENGINE|PREVIEW)_PORT\s*=\s*(\d{1,5})",
            document.text,
        )
        if 1 <= int(match.group(1)) <= 65535
    }
    return tuple(sorted(values))


def inventory_playwright_scenarios(
    repository_root: Path,
    *,
    selected_projects: tuple[str, ...],
) -> PlaywrightScenarioInventory:
    """Parse every Playwright test source and inspect production harness declarations."""
    root = repository_root.resolve()
    config_path = root / "apps/ui/e2e/playwright.config.ts"
    if not config_path.is_file():
        raise FileNotFoundError(config_path)
    config = load_document(root, config_path)
    projects = parse_playwright_projects(config)
    selected = frozenset(selected_projects)
    scenarios = tuple(
        scenario
        for path in sorted((root / "apps/ui/e2e/specs").glob("*.ts"))
        if path.is_file()
        for scenario in _scenario_metadata(load_document(root, path), projects, selected)
    )
    engine_path = root / "apps/ui/e2e/harness/engine-process.ts"
    engine = load_document(root, engine_path) if engine_path.is_file() else None
    env_path = root / "apps/ui/e2e/harness/e2e-env.ts"
    environment = load_document(root, env_path) if env_path.is_file() else None
    config_compact = re.sub(r"\s+", " ", config.text)
    engine_compact = re.sub(r"\s+", " ", engine.text) if engine else ""
    frontend_production = (
        "npm run build" in config_compact
        and "npm run preview" in config_compact
        and "npm run dev" not in config_compact
    )
    engine_production = bool(
        re.search(r"[\"']-m[\"']\s*,\s*[\"']engine\.server[\"']", engine_compact)
    )
    return PlaywrightScenarioInventory(
        scenarios=scenarios,
        frontend_startup_is_production=frontend_production,
        engine_startup_is_production=engine_production,
        harness_cleanup_kills_by_port="killPort(" in engine_compact,
        required_loopback_ports=_port_constants(environment),
    )
