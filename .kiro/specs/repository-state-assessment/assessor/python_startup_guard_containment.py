"""Install one proof-producing Python startup guard per command lease.

This is the shared mechanism behind every network-containment adapter. A subclass
supplies only the exact `NetworkMode` it serves and whether loopback is permitted;
lease allocation, guard installation, verification, and cleanup stay identical so
the stricter mode can never accidentally become the weaker one.
"""

from __future__ import annotations

import re
import secrets
import shutil
from pathlib import Path

from .contained_process_protocols import NetworkContainmentLease
from .execution_models import CheckPlan
from .model_types import NetworkMode
from .python_startup_network_guard_source import build_network_guard_source

_TOKEN = re.compile(r"[A-Za-z0-9._-]+")
_SITE_SUPPRESSORS = frozenset({"-E", "-I", "-S"})
_KNOWN_UNGUARDED = frozenset(
    {"node", "node.exe", "npm", "npm.cmd", "pnpm", "pnpm.cmd", "yarn", "yarn.cmd"}
)


class PythonStartupGuardContainment:
    """Prepare one lease-bound startup guard for the mode a subclass declares."""

    required_mode: NetworkMode = NetworkMode.LOOPBACK_ONLY
    allow_loopback: bool = True

    def __init__(self, temporary_root: Path) -> None:
        self._temporary_root = temporary_root

    def establish(
        self, plan: CheckPlan, ownership_token: str
    ) -> NetworkContainmentLease:
        """Prepare a guard; this does not itself claim that the guard loaded."""
        if not _TOKEN.fullmatch(ownership_token):  # Control: safe lease paths.
            return NetworkContainmentLease(False, None)
        if plan.network_policy.mode is not self.required_mode:  # Control: exact policy.
            return NetworkContainmentLease(False, None)
        if plan.network_policy.permits_non_loopback:  # Control: reject policy contradiction.
            return NetworkContainmentLease(False, None)
        argv = plan.exact_argv.values if plan.exact_argv is not None else ()
        if not is_guardable_python_command(argv):  # Control: known unguarded paths never launch.
            return NetworkContainmentLease(False, None)
        try:
            root = self._temporary_root.resolve(strict=True)  # Control: owned run root.
            cwd = Path(plan.cwd).resolve(strict=True)  # Control: real child cwd.
            if not root.is_dir() or not cwd.is_relative_to(root):  # Control: no path escape.
                return NetworkContainmentLease(False, None)
            hooks = (cwd / "sitecustomize.py", cwd / "usercustomize.py")
            if any(path.exists() for path in hooks):  # Control: no startup-hook shadowing.
                return NetworkContainmentLease(False, None)
            base = root / "network-containment"
            guards = base / "guards"
            observations = base / "observations"
            releases = base / "releases"
            guards.mkdir(parents=True, exist_ok=True)  # Control: assessor guard root.
            observations.mkdir(parents=True, exist_ok=True)  # Control: quarantined proof root.
            releases.mkdir(parents=True, exist_ok=True)  # Control: assessor release root.
            guard = guards / ownership_token
            guard.mkdir(exist_ok=False)  # Control: no lease reuse.
            record = observations / f"{ownership_token}.jsonl"
            record.touch(exist_ok=False)  # Control: stale evidence cannot be overwritten.
            release = releases / f"{ownership_token}.release"
            if release.exists():  # Control: stale release cannot authorize this lease.
                raise OSError("stale containment release exists")
            proof_token = secrets.token_urlsafe(32)  # Control: unpredictable per-lease identity.
            # Control: the check receives neither token nor marker path in argv/environment;
            # guarded Python user code cannot run until this assessor-owned, out-of-mirror
            # marker is validated, so it cannot self-certify in the practical threat model.
            source = build_network_guard_source(
                record, release, proof_token, allow_loopback=self.allow_loopback
            )
            compile(source, "sitecustomize.py", "exec")  # Control: syntactically valid guard.
            startup = guard / "sitecustomize.py"
            startup.write_text(source, encoding="utf-8", newline="\n")  # Control: install guard.
            if startup.read_text(encoding="utf-8") != source:  # Control: verify guard bytes.
                raise OSError("network guard verification failed")
            observation_ref = record.relative_to(root).as_posix()
            release_ref = release.relative_to(root).as_posix()
            updates = (("PYTHONPATH", str(guard)),)  # Control: child-only startup injection.
            return NetworkContainmentLease(
                True, observation_ref, updates, True, proof_token, release_ref
            )
        except (OSError, SyntaxError, UnicodeError, ValueError):
            _remove_failed_install(self._temporary_root, ownership_token)
            return NetworkContainmentLease(False, None)

    def release(self, lease: NetworkContainmentLease) -> None:
        """Remove startup and release code while preserving proof observations."""
        guard_text = dict(lease.environment_updates).get("PYTHONPATH")
        if guard_text is None:
            return
        try:
            root = self._temporary_root.resolve(strict=True)  # Control: cleanup root.
            guard = Path(guard_text).resolve(strict=True)  # Control: exact leased guard.
            owned = root / "network-containment" / "guards"
            if not guard.is_relative_to(owned):  # Control: no cleanup escape.
                return
            (guard / "sitecustomize.py").unlink(missing_ok=True)  # Control: leased hook only.
            guard.rmdir()  # Control: leased empty directory only.
            if lease.release_ref:
                release = root / lease.release_ref
                release.unlink(missing_ok=True)  # Control: leased release only.
        except OSError:
            return


def is_guardable_python_command(argv: tuple[str, ...]) -> bool:
    """Return whether a command may safely attempt empirical Python proof."""
    if not argv:  # Control: no executable means no proof path.
        return False
    name = Path(argv[0]).name.casefold()
    if name in _KNOWN_UNGUARDED:  # Control: known non-Python payloads stay pre-launch blocked.
        return False
    if any(argument in _SITE_SUPPRESSORS for argument in argv[1:]):
        return False  # Control: explicit site suppression stays pre-launch blocked.
    native_ruff = name in {"uv", "uv.exe"} and _uv_target(argv) in {"ruff", "ruff.exe"}
    return not native_ruff  # Control: native Ruff cannot produce a Python startup proof.


def _uv_target(argv: tuple[str, ...]) -> str | None:
    try:
        run_index = argv.index("run")
    except ValueError:
        return None
    for argument in argv[run_index + 1:]:
        if not argument.startswith("-"):
            return Path(argument).name.casefold()
    return None


def _remove_failed_install(temporary_root: Path, ownership_token: str) -> None:
    try:
        root = temporary_root.resolve(strict=True)  # Control: rollback root.
        guard = root / "network-containment" / "guards" / ownership_token
        record = root / "network-containment" / "observations" / f"{ownership_token}.jsonl"
        release = root / "network-containment" / "releases" / f"{ownership_token}.release"
        record.unlink(missing_ok=True)  # Control: failed lease evidence only.
        release.unlink(missing_ok=True)  # Control: failed lease release only.
        if guard.is_dir():
            shutil.rmtree(guard)  # Control: failed lease guard only.
    except OSError:
        return
