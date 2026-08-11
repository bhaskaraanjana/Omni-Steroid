"""Collect non-sensitive operating-system and hardware facts with stdlib probes.

These probes do not invoke provider APIs, open capture devices, or mutate host state.
Only hardware that can be safely identified is returned.
"""

from __future__ import annotations

import ctypes
import os
import platform

from .baseline_models import HardwareInventory, OperatingSystemInventory


def collect_operating_system_inventory() -> OperatingSystemInventory:
    """Return host name, release, and build/version without shell execution."""
    return OperatingSystemInventory(
        name=platform.system() or "unknown",
        version=platform.release() or "unknown",
        build=platform.version() or None,
    )


def collect_hardware_inventory() -> tuple[HardwareInventory, ...]:
    """Return safely detected CPU and physical-memory facts.

    GPU and audio devices are intentionally absent unless a later explicit native
    preflight detects them; this baseline probe never opens a device.
    """
    cpu_name = platform.processor() or platform.machine() or "unknown"
    inventory = [
        HardwareInventory(
            category="cpu",
            name=cpu_name,
            attributes=(
                ("architecture", platform.machine() or "unknown"),
                ("logical_processors", str(os.cpu_count() or "unknown")),
            ),
        )
    ]
    total_memory = _total_physical_memory_bytes()
    if total_memory is not None:
        inventory.append(
            HardwareInventory(
                category="memory",
                name="physical memory",
                attributes=(("total_bytes", str(total_memory)),),
            )
        )
    return tuple(inventory)


class _WindowsMemoryStatus(ctypes.Structure):
    """Native Windows ``MEMORYSTATUSEX`` layout for a read-only memory query."""

    _fields_ = (
        ("length", ctypes.c_ulong),
        ("memory_load", ctypes.c_ulong),
        ("total_physical", ctypes.c_ulonglong),
        ("available_physical", ctypes.c_ulonglong),
        ("total_page_file", ctypes.c_ulonglong),
        ("available_page_file", ctypes.c_ulonglong),
        ("total_virtual", ctypes.c_ulonglong),
        ("available_virtual", ctypes.c_ulonglong),
        ("available_extended_virtual", ctypes.c_ulonglong),
    )


def _total_physical_memory_bytes() -> int | None:
    if os.name == "nt":
        status = _WindowsMemoryStatus()
        status.length = ctypes.sizeof(status)
        try:
            succeeded = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        except (AttributeError, OSError):
            return None
        return int(status.total_physical) if succeeded else None
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        physical_pages = os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None
    total = int(page_size) * int(physical_pages)
    return total if total > 0 else None
