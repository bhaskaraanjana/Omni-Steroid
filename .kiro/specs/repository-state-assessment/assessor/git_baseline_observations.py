"""Read Git head and workspace facts through side-effect-free porcelain commands.

This is the Git stage of baseline collection: every command runs with optional locks
disabled so observing the repository never refreshes or rewrites the index, and the
raw porcelain output is decoded into the typed head and workspace-change records the
collector assembles into a baseline.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .baseline_collection_errors import BaselineCollectionError
from .baseline_models import RepositoryHead, RepositoryHeadKind, WorkspaceChange


def read_git_output(root: Path, *args: str) -> bytes:
    """Run one read-only Git command in ``root`` and return its raw stdout bytes.

    Raises ``BaselineCollectionError`` when Git cannot be started, times out, or exits
    non-zero; callers never see a partially-observed result.
    """
    try:
        result = subprocess.run(
            ("git", "--no-optional-locks", *args),
            cwd=root,
            env=_git_environment(),
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BaselineCollectionError(f"Git observation failed for {args[0]}: {error}") from error
    return result.stdout


def decode_git_path(value: bytes) -> str:
    """Decode one Git path record to a forward-slash path, preserving undecodable bytes."""
    return value.decode("utf-8", errors="surrogateescape").replace("\\", "/")


def read_git_paths(root: Path, *args: str) -> tuple[str, ...]:
    """Return the sorted decoded paths from a NUL-separated Git listing command."""
    return tuple(
        sorted(
            decode_git_path(item)
            for item in read_git_output(root, *args).split(b"\0")
            if item
        )
    )


def read_repository_head(root: Path) -> RepositoryHead:
    """Describe HEAD as a named branch when symbolic, otherwise as a detached commit."""
    commit = read_git_output(root, "rev-parse", "HEAD").decode("ascii").strip()
    try:
        branch = read_git_output(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    except BaselineCollectionError:
        return RepositoryHead(commit, RepositoryHeadKind.DETACHED)
    return RepositoryHead(commit, RepositoryHeadKind.BRANCH, decode_git_path(branch).strip())


def parse_porcelain_v2_status(
    output: bytes,
) -> tuple[tuple[WorkspaceChange, ...], tuple[WorkspaceChange, ...], tuple[str, ...]]:
    """Split ``status --porcelain=v2 -z`` output into staged, unstaged, and untracked.

    Raises ``BaselineCollectionError`` when a rename record omits the trailing original
    path it promises, since a truncated status cannot be reported as a full observation.
    """
    staged: list[WorkspaceChange] = []
    unstaged: list[WorkspaceChange] = []
    untracked: list[str] = []
    records = output.split(b"\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if record.startswith(b"? "):
            untracked.append(decode_git_path(record[2:]))
            continue
        if record.startswith(b"1 "):
            fields = record.split(b" ", 8)
            xy, path = fields[1].decode("ascii"), decode_git_path(fields[8])
            original = None
        elif record.startswith(b"2 "):
            fields = record.split(b" ", 9)
            xy, path = fields[1].decode("ascii"), decode_git_path(fields[9])
            if index >= len(records):
                raise BaselineCollectionError("rename status omitted its original path")
            original = decode_git_path(records[index])
            index += 1
        elif record.startswith(b"u "):
            fields = record.split(b" ", 10)
            xy, path = fields[1].decode("ascii"), decode_git_path(fields[10])
            original = None
        else:
            continue
        change = WorkspaceChange(path=path, status_code=xy, original_path=original)
        if xy[0] != ".":
            staged.append(change)
        if xy[1] != ".":
            unstaged.append(change)
    return tuple(staged), tuple(unstaged), tuple(sorted(untracked))


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"  # preservation control: no index refresh lock.
    environment["LC_ALL"] = "C"
    return environment
