"""Enforce total socket denial for `NetworkMode.NONE` hardware/native checks.

Hardware and native procedures declare `NetworkMode.NONE`: they have no legitimate
destination outside their own process. Serving them with the loopback adapter would
require relaxing their declared policy, so this adapter supplies the stricter guard
instead and reuses the identical per-lease startup-proof handshake.

The one admissible destination is a loopback port this same process is listening on,
because that is how CPython implements `socket.socketpair` — and therefore the asyncio
self-pipe — on Windows. A local service on any other port stays unreachable, so this
permits strictly less than loopback-only containment.
"""

from __future__ import annotations

from .model_types import NetworkMode
from .python_startup_guard_containment import PythonStartupGuardContainment

NO_EGRESS_UNAVAILABLE_REASON = (
    "empirical no-egress containment is unavailable: no unique current-lease "
    "Python startup proof can be established for this procedure"
)


class NoEgressNetworkContainment(PythonStartupGuardContainment):
    """Install one proof-producing deny-all Python socket guard per lease."""

    required_mode = NetworkMode.NONE
    # Control: no destination outside this process; other loopback ports are denied too.
    allow_loopback = False
