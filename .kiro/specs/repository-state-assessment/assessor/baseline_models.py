"""Typed baseline and file-manifest records captured before assessment execution.

The models retain working-tree identity and hashes without interpreting file contents.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import cast

from .model_types import ZonedTimestamp


@dataclass(frozen=True, slots=True)
class WorkspaceChange:
    """A lossless Git status entry for one workspace path."""

    path: str
    status_code: str
    original_path: str | None = None


@dataclass(frozen=True, slots=True)
class OperatingSystemInventory:
    """Host operating-system identity recorded at baseline."""

    name: str
    version: str
    build: str | None = None


@dataclass(frozen=True, slots=True)
class HardwareInventory:
    """One detected hardware item with non-sensitive attributes."""

    category: str
    name: str
    attributes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ToolVersion:
    """A selected assessment tool and its observed version."""

    name: str
    version: str
    executable: str


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One pre-existing path and its byte-preservation metadata."""

    path: str
    size_bytes: int
    sha256: str
    tracked: bool
    sensitive_category: str | None = None

    def __post_init__(self) -> None:
        """Validate non-negative size and canonical SHA-256 text."""
        if self.size_bytes < 0:
            raise ValueError("manifest size must be non-negative")
        if len(self.sha256) != 64 or any(character not in "0123456789abcdef" for character in self.sha256):
            raise ValueError("manifest sha256 must be 64 lowercase hexadecimal characters")


@dataclass(frozen=True, slots=True)
class FileManifest:
    """An immutable source or mirror file-manifest snapshot."""

    manifest_id: str
    kind: str
    created_at: ZonedTimestamp
    entries: tuple[ManifestEntry, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation containing metadata only."""
        return {
            "manifest_id": self.manifest_id,
            "kind": self.kind,
            "created_at": self.created_at.value.isoformat(),
            "entries": [
                {
                    "path": entry.path,
                    "size_bytes": entry.size_bytes,
                    "sha256": entry.sha256,
                    "tracked": entry.tracked,
                    "sensitive_category": entry.sensitive_category,
                }
                for entry in self.entries
            ],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "FileManifest":
        """Reconstruct a manifest losslessly from ``to_dict`` output."""
        return cls(
            manifest_id=cast(str, value["manifest_id"]),
            kind=cast(str, value["kind"]),
            created_at=ZonedTimestamp(
                datetime.fromisoformat(cast(str, value["created_at"]))
            ),
            entries=tuple(
                _manifest_entry_from_value(item)
                for item in _sequence(value["entries"])
            ),
        )


@dataclass(frozen=True, slots=True)
class AssessmentBaseline:
    """Complete reproducibility and preservation state captured at run start."""

    run_id: str
    repository_root: str
    head: "RepositoryHead"
    started_at: ZonedTimestamp
    staged_changes: tuple[WorkspaceChange, ...]
    unstaged_changes: tuple[WorkspaceChange, ...]
    untracked_paths: tuple[str, ...]
    operating_system: OperatingSystemInventory
    hardware: tuple[HardwareInventory, ...]
    tools: tuple[ToolVersion, ...]
    source_manifest_ref: str
    designated_roots: tuple[str, ...]
    mirror_manifest_ref: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation without dropping empty values."""
        return {
            "run_id": self.run_id,
            "repository_root": self.repository_root,
            "head": {
                "commit": self.head.commit,
                "kind": self.head.kind.value,
                "branch_name": self.head.branch_name,
            },
            "started_at": self.started_at.value.isoformat(),
            "staged_changes": [_change_to_dict(change) for change in self.staged_changes],
            "unstaged_changes": [_change_to_dict(change) for change in self.unstaged_changes],
            "untracked_paths": list(self.untracked_paths),
            "operating_system": {
                "name": self.operating_system.name,
                "version": self.operating_system.version,
                "build": self.operating_system.build,
            },
            "hardware": [
                {
                    "category": item.category,
                    "name": item.name,
                    "attributes": [list(attribute) for attribute in item.attributes],
                }
                for item in self.hardware
            ],
            "tools": [
                {
                    "name": tool.name,
                    "version": tool.version,
                    "executable": tool.executable,
                }
                for tool in self.tools
            ],
            "source_manifest_ref": self.source_manifest_ref,
            "designated_roots": list(self.designated_roots),
            "mirror_manifest_ref": self.mirror_manifest_ref,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "AssessmentBaseline":
        """Reconstruct a baseline from the representation produced by ``to_dict``."""
        head = _mapping(value["head"])
        operating_system = _mapping(value["operating_system"])
        hardware = _sequence(value["hardware"])
        tools = _sequence(value["tools"])
        return cls(
            run_id=cast(str, value["run_id"]),
            repository_root=cast(str, value["repository_root"]),
            head=RepositoryHead(
                commit=cast(str, head["commit"]),
                kind=RepositoryHeadKind(cast(str, head["kind"])),
                branch_name=cast(str | None, head["branch_name"]),
            ),
            started_at=ZonedTimestamp(datetime.fromisoformat(cast(str, value["started_at"]))),
            staged_changes=_changes_from_value(value["staged_changes"]),
            unstaged_changes=_changes_from_value(value["unstaged_changes"]),
            untracked_paths=tuple(cast(Sequence[str], _sequence(value["untracked_paths"]))),
            operating_system=OperatingSystemInventory(
                name=cast(str, operating_system["name"]),
                version=cast(str, operating_system["version"]),
                build=cast(str | None, operating_system["build"]),
            ),
            hardware=tuple(_hardware_from_value(item) for item in hardware),
            tools=tuple(_tool_from_value(item) for item in tools),
            source_manifest_ref=cast(str, value["source_manifest_ref"]),
            designated_roots=tuple(
                cast(Sequence[str], _sequence(value["designated_roots"]))
            ),
            mirror_manifest_ref=cast(str | None, value["mirror_manifest_ref"]),
        )


class RepositoryHeadKind(StrEnum):
    """Whether baseline HEAD names a branch or is detached."""

    BRANCH = "branch"
    DETACHED = "detached"


@dataclass(frozen=True, slots=True)
class RepositoryHead:
    """Exact source revision plus mutually exclusive branch/detached state."""

    commit: str
    kind: RepositoryHeadKind
    branch_name: str | None = None

    def __post_init__(self) -> None:
        """Require a branch name only for branch state."""
        has_branch = self.branch_name is not None and bool(self.branch_name.strip())
        if (self.kind is RepositoryHeadKind.BRANCH) != has_branch:
            raise ValueError("branch_name must be set only when HEAD kind is branch")

    def render(self) -> str:
        """Render branch or detached state without losing the exact commit."""
        if self.kind is RepositoryHeadKind.BRANCH:
            return f"branch {self.branch_name} ({self.commit})"
        return f"detached HEAD ({self.commit})"


def _manifest_entry_from_value(value: object) -> ManifestEntry:
    entry = _mapping(value)
    return ManifestEntry(
        path=cast(str, entry["path"]),
        size_bytes=cast(int, entry["size_bytes"]),
        sha256=cast(str, entry["sha256"]),
        tracked=cast(bool, entry["tracked"]),
        sensitive_category=cast(str | None, entry["sensitive_category"]),
    )


def _change_to_dict(change: WorkspaceChange) -> dict[str, object]:
    return {
        "path": change.path,
        "status_code": change.status_code,
        "original_path": change.original_path,
    }


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("serialized baseline object must be a mapping")
    return cast(Mapping[str, object], value)


def _sequence(value: object) -> Sequence[object]:
    if not isinstance(value, list):
        raise TypeError("serialized baseline collection must be a list")
    return value


def _changes_from_value(value: object) -> tuple[WorkspaceChange, ...]:
    changes = []
    for item in _sequence(value):
        change = _mapping(item)
        changes.append(
            WorkspaceChange(
                path=cast(str, change["path"]),
                status_code=cast(str, change["status_code"]),
                original_path=cast(str | None, change["original_path"]),
            )
        )
    return tuple(changes)


def _hardware_from_value(value: object) -> HardwareInventory:
    item = _mapping(value)
    attributes = tuple(
        (cast(str, pair[0]), cast(str, pair[1]))
        for pair in (_sequence(attribute) for attribute in _sequence(item["attributes"]))
    )
    return HardwareInventory(
        category=cast(str, item["category"]),
        name=cast(str, item["name"]),
        attributes=attributes,
    )


def _tool_from_value(value: object) -> ToolVersion:
    tool = _mapping(value)
    return ToolVersion(
        name=cast(str, tool["name"]),
        version=cast(str, tool["version"]),
        executable=cast(str, tool["executable"]),
    )
