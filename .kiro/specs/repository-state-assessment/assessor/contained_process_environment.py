"""Build secret-free child environments and reject non-terminating commands.

The runner inherits only named toolchain variables and redirects common writable
homes, caches, temporary files, and build products beneath the temporary run root.
It never adds offline/frozen flags because doing so could change repository semantics.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from .execution_models import CheckPlan

_INHERITED_NAMES = frozenset(
    name.casefold()
    for name in (
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "PROCESSOR_IDENTIFIER",
        "LANG",
        "LC_ALL",
        "TZ",
        "VCINSTALLDIR",
        "VSINSTALLDIR",
        "INCLUDE",
        "LIB",
        "LIBPATH",
        "WindowsSdkDir",
        "UCRTVersion",
        "VCToolsInstallDir",
        "VIRTUAL_ENV",
    )
)
_SECRET_NAME = re.compile(
    r"(?:api[_-]?key|token|secret|password|credential|authorization|oauth|cookie)",
    re.IGNORECASE,
)
_WATCH_TOKENS = frozenset({"watch", "--watch", "--watch=true", "-w"})


def require_terminating_command(plan: CheckPlan) -> None:
    """Reject watch flags and known development-server invocations before launch."""
    if plan.exact_argv is None:
        raise ValueError("contained process runner requires an exact argument vector")
    tokens = tuple(value.strip().casefold() for value in plan.exact_argv.values)
    arguments = frozenset(tokens[1:])
    package_runner = tokens[0].endswith(
        ("npm", "npm.cmd", "pnpm", "pnpm.cmd", "yarn", "yarn.cmd")
    )
    dev_script = package_runner and (
        tokens[1:3] in (("run", "dev"), ("run", "serve"))
        or tokens[1:2] in (("dev",), ("serve",))
    )
    direct_dev_server = any(
        pattern
        for pattern in (
            tokens[0].endswith(("vite", "vite.cmd")) and "preview" not in arguments,
            tokens[0].endswith(("next", "next.cmd")) and "dev" in arguments,
            tokens[0].endswith(("webpack", "webpack.cmd")) and "serve" in arguments,
            tokens[0].endswith(("uvicorn", "uvicorn.exe")) and "--reload" in arguments,
            tokens[0].endswith(("cargo", "cargo.exe")) and "watch" in arguments,
        )
    )
    if arguments & _WATCH_TOKENS or dev_script or direct_dev_server:
        raise ValueError("non-terminating watch or development-server mode is prohibited")


def build_contained_environment(
    temporary_root: Path,
    ownership_token: str,
    safe_parent_environment: Mapping[str, str],
) -> dict[str, str]:
    """Return an allowlisted environment with every standard writable path redirected."""
    environment = {
        name: value
        for name, value in safe_parent_environment.items()
        if name.casefold() in _INHERITED_NAMES
        and not _SECRET_NAME.search(name)
        and isinstance(value, str)
        and value
    }
    data_root = temporary_root / "process-data" / ownership_token
    directories = {
        "HOME": data_root / "home",
        "USERPROFILE": data_root / "home",
        "APPDATA": data_root / "appdata" / "roaming",
        "LOCALAPPDATA": data_root / "appdata" / "local",
        "TEMP": data_root / "temp",
        "TMP": data_root / "temp",
        "UV_CACHE_DIR": data_root / "cache" / "uv",
        "PYTHONPYCACHEPREFIX": data_root / "cache" / "python",
        "MYPY_CACHE_DIR": data_root / "cache" / "mypy",
        "npm_config_cache": data_root / "cache" / "npm",
        "npm_config_store_dir": data_root / "cache" / "pnpm-store",
        "PNPM_HOME": data_root / "cache" / "pnpm-home",
        "PNPM_STORE_DIR": data_root / "cache" / "pnpm-store",
        "CARGO_HOME": data_root / "cache" / "cargo-home",
        "CARGO_TARGET_DIR": data_root / "build" / "cargo-target",
        "XDG_CACHE_HOME": data_root / "cache" / "xdg",
        "XDG_DATA_HOME": data_root / "data" / "xdg",
        "PLAYWRIGHT_OUTPUT_DIR": data_root / "artifacts" / "playwright",
    }
    for directory in frozenset(directories.values()):
        directory.mkdir(parents=True, exist_ok=False)
    for directory in (
        data_root / "data" / "models",
        data_root / "data" / "vault",
        data_root / "artifacts" / "e2e",
    ):
        directory.mkdir(parents=True, exist_ok=False)
    environment.update({name: str(path) for name, path in directories.items()})
    environment.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_ADDOPTS": "-p no:cacheprovider",
            "UV_OFFLINE": "1",
            "COVERAGE_FILE": str(data_root / "artifacts" / ".coverage"),
            "OMNI_ASSESSMENT_OWNERSHIP_TOKEN": ownership_token,
            "OMNI_DB_PATH": str(data_root / "data" / "omni.db"),
            "OMNI_MODELS_DIR": str(data_root / "data" / "models"),
            "OMNI_VAULT_DIR": str(data_root / "data" / "vault"),
            "OMNI_E2E_RUN_DIR": str(data_root / "artifacts" / "e2e"),
            "OMNI_E2E_ALLOW_NO_KEYS": "1",
            "OMNI_ENV_FILE": str(data_root / "absent-provider-credentials.env"),
        }
    )
    return environment
