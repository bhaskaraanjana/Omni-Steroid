"""Sequence the read-only baseline stages into one immutable assessment baseline.

This is the entry point of baseline collection: it drives the Git observation, source
manifest hashing, and tool probing stages, and owns the path-only sensitivity
vocabulary those stages label entries with. Reports receive hashes, sizes, and
path-derived labels, never file bytes or content-derived classifications.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from .baseline_collection_errors import BaselineCollectionError
from .baseline_models import (
    AssessmentBaseline,
    FileManifest,
    HardwareInventory,
    OperatingSystemInventory,
)
from .git_baseline_observations import (
    parse_porcelain_v2_status,
    read_git_output,
    read_git_paths,
    read_repository_head,
)
from .host_inventory import (
    collect_hardware_inventory,
    collect_operating_system_inventory,
)
from .model_types import ZonedTimestamp
from .security_records import SensitiveCategory
from .source_manifest_hashing import collect_source_manifest
from .tool_version_probing import ToolProbe, probe_tool_versions


@dataclass(frozen=True, slots=True)
class CollectedBaseline:
    """Baseline metadata paired with the exact source manifest it references."""

    baseline: AssessmentBaseline
    source_manifest: FileManifest


class BaselineCollector:
    """Read Git, host, tool, and file facts without writing to the repository."""

    def __init__(
        self,
        *,
        clock: Callable[[], ZonedTimestamp] | None = None,
        operating_system_provider: Callable[[], OperatingSystemInventory] | None = None,
        hardware_provider: Callable[[], tuple[HardwareInventory, ...]] | None = None,
    ) -> None:
        self._clock = clock or _local_zoned_now
        self._operating_system_provider = (
            operating_system_provider or collect_operating_system_inventory
        )
        self._hardware_provider = hardware_provider or collect_hardware_inventory

    def collect(
        self,
        repository_root: str | Path,
        *,
        run_id: str,
        designated_roots: tuple[str, ...],
        source_manifest_ref: str,
        tool_probes: tuple[ToolProbe, ...] = (),
    ) -> CollectedBaseline:
        """Collect one immutable baseline and manifest from current on-disk bytes.

        Failure modes are explicit: a missing repository, Git observation error, or
        unreadable pre-existing file raises ``BaselineCollectionError``.
        """
        root = Path(repository_root).resolve(strict=True)
        if not root.is_dir():
            raise BaselineCollectionError(f"repository root is not a directory: {root}")
        started_at = self._clock()
        status = read_git_output(
            root, "status", "--porcelain=v2", "-z", "--untracked-files=all"
        )
        staged, unstaged, untracked = parse_porcelain_v2_status(status)
        head = read_repository_head(root)
        tracked_paths = read_git_paths(root, "ls-files", "-z", "--cached")
        untracked_paths = read_git_paths(
            root, "ls-files", "-z", "--others", "--exclude-standard"
        )
        manifest = collect_source_manifest(
            root,
            tracked_paths=tracked_paths,
            untracked_paths=untracked_paths,
            manifest_id=f"{run_id}-source",
            created_at=started_at,
            classify_sensitive_path=BaselineCollector.classify_sensitive_path,
        )
        tool_versions = probe_tool_versions(
            (ToolProbe("Git", ("git", "--version")), *tool_probes), root
        )
        baseline = AssessmentBaseline(
            run_id=run_id,
            repository_root=str(root),
            head=head,
            started_at=started_at,
            staged_changes=staged,
            unstaged_changes=unstaged,
            untracked_paths=untracked,
            operating_system=self._operating_system_provider(),
            hardware=self._hardware_provider(),
            tools=tool_versions,
            source_manifest_ref=source_manifest_ref,
            designated_roots=designated_roots,
        )
        return CollectedBaseline(baseline, manifest)

    @staticmethod
    def classify_sensitive_path(path: str) -> str | None:
        """Label a sensitive file using its normalized path only, never its content."""
        normalized = path.replace("\\", "/").casefold()
        parts = tuple(part for part in normalized.split("/") if part)
        name = parts[-1] if parts else ""
        suffix = PurePosixPath(name).suffix
        if suffix in {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".wma"}:
            return SensitiveCategory.PRIVATE_AUDIO.value
        if any("transcript" in part for part in parts):
            return SensitiveCategory.PRIVATE_TRANSCRIPT.value
        credential_suffixes = {".pem", ".key", ".p12", ".pfx", ".kdbx"}
        credential_terms = ("credential", "secret", "token", "private-key", "service-account")
        if (
            name == ".env"
            or name.startswith(".env.")
            or suffix in credential_suffixes
            or any(term in part for part in parts for term in credential_terms)
        ):
            return SensitiveCategory.CREDENTIAL.value
        return None


def _local_zoned_now() -> ZonedTimestamp:
    return ZonedTimestamp(datetime.now().astimezone())
