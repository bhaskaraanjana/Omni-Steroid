"""Production snapshot-diff auditing for writes inside a temporary run tree."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .contained_process_protocols import WriteAuditOutcome
from .contained_runner_support import safe_file_part
from .execution_models import CheckPlan

_TOKEN = re.compile(r"[A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class _AuditHandle:
    """Immutable baseline and policy for one owned command attempt."""

    token: str
    designated_roots: tuple[Path, ...]
    excluded_paths: frozenset[str]
    before: dict[str, str]


class ObservedWriteAuditor:
    """Hash the complete temporary tree and reject writes outside designated roots."""

    def __init__(self, temporary_root: Path, *, observation_name: str = "write-audit") -> None:
        self._temporary_root = temporary_root
        # Control: each auditor owns an exclusive evidence root, so two phases monitoring
        # the same run tree keep separate audit trails instead of sharing or overwriting one.
        self._observation_root = temporary_root / observation_name
        self.available = self._establish()  # Control: unavailable auditing blocks launch.

    def start(self, plan: CheckPlan, ownership_token: str) -> object:
        """Capture a complete pre-launch hash baseline for the temporary tree."""
        if not self.available:  # Control: never proceed after failed establishment.
            raise OSError("write auditing is unavailable")
        if _TOKEN.fullmatch(ownership_token) is None:  # Control: safe evidence filename.
            raise OSError("unsafe write-audit ownership token")
        root = self._temporary_root.resolve(strict=True)  # Control: fixed monitored root.
        designated: list[Path] = []
        for text in plan.write_policy.designated_roots:
            candidate = Path(text)
            if candidate.is_symlink():  # Control: no designated-root redirection.
                raise OSError("designated write root is symbolic")
            resolved = candidate.resolve(strict=True)  # Control: existing write root.
            if resolved == root or not resolved.is_relative_to(root):  # Control: narrow writes.
                raise OSError("designated write root escapes temporary root")
            designated.append(resolved)
        if not designated:  # Control: explicit write destinations required.
            raise OSError("no designated write roots")
        excluded = _assessor_artifacts(plan.check_id, ownership_token)
        before = self._snapshot(root, excluded)  # Control: baseline precedes process creation.
        return _AuditHandle(ownership_token, tuple(designated), excluded, before)

    def finish(self, handle: object) -> WriteAuditOutcome:
        """Persist all created, modified, and deleted files with before/after hashes."""
        if not isinstance(handle, _AuditHandle):  # Control: reject foreign audit state.
            return WriteAuditOutcome(False, None)
        try:
            root = self._temporary_root.resolve(strict=True)  # Control: same monitored root.
            after = self._snapshot(root, handle.excluded_paths)  # Control: post-cleanup snapshot.
            paths = sorted(handle.before.keys() | after.keys())
            changes: list[dict[str, str | bool | None]] = []
            outside: list[str] = []
            for relative in paths:
                before_hash = handle.before.get(relative)
                after_hash = after.get(relative)
                if before_hash == after_hash:  # Control: unchanged paths are not writes.
                    continue
                disposition = (
                    "created" if before_hash is None
                    else "deleted" if after_hash is None
                    else "modified"
                )
                absolute = root / relative  # Control: classify against resolved policy roots.
                inside = any(
                    absolute == allowed or absolute.is_relative_to(allowed)
                    for allowed in handle.designated_roots
                )
                if not inside:  # Control: every out-of-policy write fails the audit.
                    outside.append(relative)
                changes.append(
                    {
                        "after_sha256": after_hash,
                        "before_sha256": before_hash,
                        "disposition": disposition,
                        "inside_designated_roots": inside,
                        "path": relative,
                    }
                )
            payload = {
                "changes": changes,
                "compliant": not outside,
                "designated_roots": [
                    path.relative_to(root).as_posix() for path in handle.designated_roots
                ],
                "outside_designated_roots": outside,
                "ownership_token": handle.token,
            }
            reference = self._persist(handle.token, payload)  # Control: quarantined evidence.
            return WriteAuditOutcome(not outside, reference)
        except (OSError, UnicodeError, ValueError):
            return WriteAuditOutcome(False, None)  # Control: incomplete audit fails closed.

    def _establish(self) -> bool:
        try:
            root = self._temporary_root
            if root.is_symlink():  # Control: reject monitored-root redirection.
                return False
            resolved = root.resolve(strict=True)  # Control: existing owned run root.
            if not resolved.is_dir():  # Control: snapshots require a real directory.
                return False
            self._observation_root.mkdir(exist_ok=False)  # Control: exclusive evidence root.
            probe = self._observation_root / ".availability-probe"
            probe.write_bytes(b"audit")  # Control: prove evidence writes are possible.
            if probe.read_bytes() != b"audit":  # Control: verify observation integrity.
                return False
            probe.unlink()  # Control: remove only assessor-owned probe.
            return True
        except OSError:
            return False

    def _snapshot(self, root: Path, excluded_paths: frozenset[str]) -> dict[str, str]:
        snapshot: dict[str, str] = {}
        observation = self._observation_root.resolve(strict=True)
        for path in root.rglob("*"):  # Control: bounded to the temporary run tree.
            if path == observation or path.is_relative_to(observation):
                continue  # Control: assessor audit evidence cannot indict the command.
            relative = path.relative_to(root).as_posix()
            if relative in excluded_paths:
                continue  # Control: exact lease-owned stdout/proof artifacts only.
            if path.is_symlink():
                target = path.readlink().as_posix().encode("utf-8")
                digest = hashlib.sha256(b"symlink\0" + target).hexdigest()
            elif path.is_file():
                digest = _hash_file(path)  # Control: content-address every observed file.
            else:
                continue
            snapshot[relative] = digest
        return snapshot

    def _persist(
        self, token: str, payload: dict[str, object]
    ) -> str:
        path = self._observation_root / f"{token}.json"
        serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)  # Control: no audit-evidence overwrite.
        if path.read_text(encoding="utf-8") != serialized:  # Control: verify persistence.
            raise OSError("write-audit evidence verification failed")
        return path.relative_to(self._temporary_root).as_posix()


def _assessor_artifacts(check_id: str, token: str) -> frozenset[str]:
    suffix = token.rsplit("-", 1)[-1]  # Control: match runner-owned evidence suffix.
    stem = f"{safe_file_part(check_id)}-{suffix}"  # Control: exact raw artifact stem.
    return frozenset(  # Control: exclude no directory or cross-lease wildcard.
        {
            f"raw/{stem}.stdout",
            f"raw/{stem}.stderr",
            f"network-containment/observations/{token}.jsonl",
            f"network-containment/releases/{token}.release",
        }
    )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:  # Control: hash bytes without executing content.
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
