"""Quarantined output, artifact, and diagnostic capture for Local E2E runs.

Every Local E2E stream, screenshot, and trace stays inside the run's temporary root
and is referenced only relative to it, so nothing outside the contained run is read
or published. It sits after process orchestration and before evidence composition.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .e2e_process_controller import E2EProcessRole
from .evidence_models import EvidenceArtifact


def configure_e2e_environment(environment: dict[str, str], browser: Path) -> None:
    """Create the report, screenshot, and trace directories inside the run root."""
    e2e_root = Path(environment["OMNI_E2E_RUN_DIR"])
    directories = {
        "OMNI_E2E_REPORT_DIR": e2e_root / "report",
        "OMNI_E2E_SCREENSHOT_DIR": e2e_root / "screenshots",
        "OMNI_E2E_TRACE_DIR": e2e_root / "traces",
    }
    for path in directories.values():
        path.mkdir(parents=True, exist_ok=False)
    environment.update({name: str(path) for name, path in directories.items()})
    environment["OMNI_E2E_BROWSER_EXECUTABLE"] = str(browser)


def allocate_output_paths(
    temporary_root: Path, ownership_token: str
) -> dict[str, Path]:
    """Return one fresh stdout/stderr path per role under the ownership token."""
    output_root = temporary_root / "raw" / "e2e" / ownership_token
    output_root.mkdir(parents=True, exist_ok=False)
    return {
        f"{role.value}_{stream}": output_root / f"{role.value}.{stream}"
        for role in E2EProcessRole
        for stream in ("stdout", "stderr")
    }


def collect_artifacts(
    environment: Mapping[str, str], temporary_root: Path
) -> tuple[EvidenceArtifact, ...]:
    """Return screenshot and trace artifacts, recording absence when none exist."""
    artifacts: list[EvidenceArtifact] = []
    for kind, variable in (
        ("screenshot", "OMNI_E2E_SCREENSHOT_DIR"),
        ("trace", "OMNI_E2E_TRACE_DIR"),
    ):
        files = sorted(
            (path for path in Path(environment[variable]).rglob("*") if path.is_file()),
            key=lambda path: path.as_posix().casefold(),
        )
        if files:
            artifacts.extend(
                EvidenceArtifact(kind, relative_ref(path, temporary_root))
                for path in files
            )
        else:
            artifacts.append(EvidenceArtifact(kind, absent=True))
    return tuple(artifacts)


def read_failure_output(paths: Mapping[str, Path]) -> tuple[str, ...]:
    """Return every captured stream line, labelled by role and stream name."""
    lines: list[str] = []
    for name, path in paths.items():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lines.extend(f"{name}: {line}" for line in text.splitlines())
    return tuple(lines)


def relative_ref(path: Path, temporary_root: Path) -> str:
    """Return one output reference relative to the contained temporary root."""
    return path.resolve(strict=False).relative_to(temporary_root).as_posix()
