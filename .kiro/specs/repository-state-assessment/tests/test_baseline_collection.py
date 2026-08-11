"""Focused examples for read-only baseline and source-manifest collection."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from assessor.baseline_collector import BaselineCollector, ToolProbe
from assessor.baseline_models import (
    FileManifest,
    HardwareInventory,
    OperatingSystemInventory,
    RepositoryHeadKind,
)
from assessor.model_types import ZonedTimestamp


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _repository_with_mixed_state(tmp_path: Path) -> tuple[Path, bytes, str]:
    repository = tmp_path / "repository with spaces"
    repository.mkdir()
    _git(repository, "init", "--initial-branch=main")
    _git(repository, "config", "user.email", "assessment@example.invalid")
    _git(repository, "config", "user.name", "Assessment Fixture")

    _write(repository / "staged.txt", "committed staged\n")
    _write(repository / "unstaged.txt", "committed unstaged\n")
    _write(repository / ".env", "DO_NOT_REPORT=this-secret-value\n")
    _git(repository, "add", "--", "staged.txt", "unstaged.txt", ".env")
    _git(repository, "commit", "-m", "fixture baseline")

    _write(repository / "staged.txt", "staged bytes\n")
    _git(repository, "add", "--", "staged.txt")
    _write(repository / "unstaged.txt", "unstaged bytes\n")
    _write(repository / "資料" / "untracked.txt", "untracked bytes\n")

    index_path = Path(_git(repository, "rev-parse", "--git-path", "index"))
    if not index_path.is_absolute():
        index_path = repository / index_path
    return repository, index_path.read_bytes(), _git(repository, "rev-parse", "HEAD")


def test_collection_captures_git_environment_and_hashes_without_index_mutation(
    tmp_path: Path,
) -> None:
    repository, index_before, commit = _repository_with_mixed_state(tmp_path)
    fixed_time = ZonedTimestamp(datetime(2026, 7, 9, 10, 11, tzinfo=timezone.utc))
    collector = BaselineCollector(
        clock=lambda: fixed_time,
        operating_system_provider=lambda: OperatingSystemInventory(
            "FixtureOS", "1.2", "345"
        ),
        hardware_provider=lambda: (
            HardwareInventory("cpu", "Fixture CPU", (("logical_processors", "8"),)),
        ),
    )

    collected = collector.collect(
        repository,
        run_id="run-fixture",
        designated_roots=("assessment-output/run-fixture",),
        source_manifest_ref="manifests/source.json",
        tool_probes=(ToolProbe("Python", (sys.executable, "--version")),),
    )

    assert collected.baseline.head.commit == commit
    assert collected.baseline.head.kind is RepositoryHeadKind.BRANCH
    assert collected.baseline.head.branch_name == "main"
    assert {change.path for change in collected.baseline.staged_changes} == {"staged.txt"}
    assert {change.path for change in collected.baseline.unstaged_changes} == {
        "unstaged.txt"
    }
    assert collected.baseline.untracked_paths == ("資料/untracked.txt",)
    assert collected.baseline.operating_system.name == "FixtureOS"
    assert collected.baseline.hardware[0].name == "Fixture CPU"
    tools = {tool.name: tool for tool in collected.baseline.tools}
    assert set(tools) == {"Git", "Python"}
    assert tools["Git"].version.startswith("git version ")
    assert tools["Python"].version.startswith("Python ")
    assert collected.baseline.started_at == fixed_time
    assert collected.source_manifest.created_at == fixed_time

    entries = {entry.path: entry for entry in collected.source_manifest.entries}
    assert entries["staged.txt"].tracked is True
    assert entries["資料/untracked.txt"].tracked is False
    assert entries["staged.txt"].sha256 == hashlib.sha256(
        (repository / "staged.txt").read_bytes()
    ).hexdigest()
    assert entries[".env"].sensitive_category == "credential"

    serialized = json.dumps(collected.source_manifest.to_dict(), ensure_ascii=False)
    assert "DO_NOT_REPORT" not in serialized
    assert "this-secret-value" not in serialized
    assert FileManifest.from_dict(json.loads(serialized)) == collected.source_manifest

    index_path = Path(_git(repository, "rev-parse", "--git-path", "index"))
    if not index_path.is_absolute():
        index_path = repository / index_path
    assert index_path.read_bytes() == index_before


def test_sensitive_classification_uses_only_normalized_path_names() -> None:
    classify = BaselineCollector.classify_sensitive_path

    assert classify("config/.env.production") == "credential"
    assert classify("keys/service-account.pem") == "credential"
    assert classify("recordings/private-session.wav") == "private_audio"
    assert classify("transcripts/interview.txt") == "private_transcript"
    assert classify("src/router.py") is None
