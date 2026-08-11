"""Generate the assessment-owned Python startup guard installed into a child.

The guard is the single place where child-process egress policy is expressed. It
denies before any socket call, appends quarantined evidence, and refuses to release
user code until the assessor validates its per-lease startup proof. One builder
serves every mode so loopback and no-egress containment cannot drift apart.
"""

from __future__ import annotations

from pathlib import Path

_LOOPBACK_PREDICATE = (
    '    if host.casefold() == "localhost": return True  # Control: explicit localhost.\n'
    "    try: return ipaddress.ip_address(host).is_loopback  # Control: 127/8 and ::1.\n"
    "    except ValueError: return False"
)

# NetworkMode.NONE means "no destination outside this process". A destination is
# admissible only when it is loopback AND the listening port was created by this very
# process, which is how CPython implements `socket.socketpair` — and therefore the
# asyncio self-pipe — on Windows. Every other loopback port, and every non-loopback
# destination, is denied. This permits strictly less than the loopback-only guard: a
# local service listening on another port remains unreachable.
_SAME_PROCESS_ONLY_PREDICATE = (
    "    try: loopback = ipaddress.ip_address(host).is_loopback\n"
    '    except ValueError: loopback = host.casefold() == "localhost"\n'
    "    port = address[1] if isinstance(address, tuple) and len(address) > 1 else None\n"
    "    return bool(loopback) and port in _SELF_LISTENING_PORTS  # Control: self-IPC only."
)


def build_network_guard_source(
    observation: Path, release: Path, token: str, *, allow_loopback: bool
) -> str:
    """Build one lease-bound startup guard for the requested egress policy."""
    predicate = _LOOPBACK_PREDICATE if allow_loopback else _SAME_PROCESS_ONLY_PREDICATE
    mode = "loopback-only" if allow_loopback else "no-egress"
    return f'''"""Assessment-owned {mode} socket guard."""
from __future__ import annotations
import datetime, ipaddress, json, os, socket, sys, time
_OBSERVATION = {str(observation)!r}
_RELEASE = {str(release)!r}
_TOKEN = {token!r}
_FIRST = (os.environ.pop("OMNI_CONTAINMENT_GUARD_ACTIVE", None) is None
          and not sys.flags.no_site)  # Control: runner startup only; -S probes never attest.
os.environ["OMNI_CONTAINMENT_GUARD_ACTIVE"] = "1"
_ORIGINAL_CONNECT = socket.socket.connect
_ORIGINAL_CONNECT_EX = socket.socket.connect_ex
_ORIGINAL_SENDTO = socket.socket.sendto
_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_ORIGINAL_GETHOSTBYNAME = socket.gethostbyname
_ORIGINAL_GETHOSTBYNAME_EX = socket.gethostbyname_ex
_ORIGINAL_GETHOSTBYADDR = socket.gethostbyaddr
_ORIGINAL_GETNAMEINFO = socket.getnameinfo
_ORIGINAL_LISTEN = socket.socket.listen
_SELF_LISTENING_PORTS = set()

def _guarded_listen(instance, *arguments):
    result = _ORIGINAL_LISTEN(instance, *arguments)
    try:
        name = instance.getsockname()  # Control: record only this process's own listener.
        if isinstance(name, tuple) and len(name) > 1 and isinstance(name[1], int):
            _SELF_LISTENING_PORTS.add(name[1])
    except OSError: pass
    return result

socket.socket.listen = _guarded_listen  # Control: same-process IPC destinations.

def _host(address):
    value = address[0] if isinstance(address, tuple) and address else None
    if isinstance(value, bytes):
        try: return value.decode("ascii")
        except UnicodeDecodeError: return None
    return value if isinstance(value, str) else None

def _allowed(address):
    host = _host(address)
    if host is None: return False
{predicate}

def _append(event):
    payload = (json.dumps(event, sort_keys=True) + "\\n").encode("utf-8")
    descriptor = os.open(_OBSERVATION, os.O_APPEND | os.O_WRONLY)  # Control: append evidence.
    try: os.write(descriptor, payload)  # Control: evidence precedes network I/O.
    finally: os.close(descriptor)

def _check(address):
    disposition = "allowed" if _allowed(address) else "denied"
    _append({{"destination": repr(address)[:512], "disposition": disposition,
             "kind": "network_attempt",
             "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}})
    if disposition == "denied":
        raise PermissionError("egress denied by assessment containment")  # Control: pre-connect.

def _guarded_connect(instance, address):
    _check(address); return _ORIGINAL_CONNECT(instance, address)
def _guarded_connect_ex(instance, address):
    _check(address); return _ORIGINAL_CONNECT_EX(instance, address)
def _guarded_sendto(instance, data, *arguments):
    _check(arguments[-1]); return _ORIGINAL_SENDTO(instance, data, *arguments)
def _guarded_getaddrinfo(host, port, *arguments, **keywords):
    _check((host, port)); return _ORIGINAL_GETADDRINFO(host, port, *arguments, **keywords)
def _guarded_lookup(original, host):
    _check((host, None)); return original(host)
def _guarded_getnameinfo(address, flags):
    _check(address); return _ORIGINAL_GETNAMEINFO(address, flags)

socket.socket.connect = _guarded_connect  # Control: connected sockets.
socket.socket.connect_ex = _guarded_connect_ex  # Control: connect_ex bypass.
socket.socket.sendto = _guarded_sendto  # Control: UDP bypass.
socket.getaddrinfo = _guarded_getaddrinfo  # Control: pre-DNS destination denial.
socket.gethostbyname = lambda host: _guarded_lookup(_ORIGINAL_GETHOSTBYNAME, host)
socket.gethostbyname_ex = lambda host: _guarded_lookup(_ORIGINAL_GETHOSTBYNAME_EX, host)
socket.gethostbyaddr = lambda host: _guarded_lookup(_ORIGINAL_GETHOSTBYADDR, host)
socket.getnameinfo = _guarded_getnameinfo  # Control: reverse-DNS bypass.

if _FIRST:
    proof = {{"destination": "guard-startup", "disposition": "guard_loaded",
             "interpreter": str(__import__("pathlib").Path(sys.executable).resolve()),
             "kind": "containment_proof", "pid": os.getpid(), "token": _TOKEN,
             "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}}
    descriptor = os.open(_OBSERVATION, os.O_APPEND | os.O_WRONLY)  # Control: leased marker.
    try:
        if os.fstat(descriptor).st_size != 0: os._exit(125)  # Control: reject stale marker.
        os.write(descriptor, (json.dumps(proof, sort_keys=True) + "\\n").encode("utf-8"))
    finally: os.close(descriptor)
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        try:
            with open(_RELEASE, encoding="utf-8") as stream:
                if stream.read().strip() == _TOKEN: break  # Control: current-lease release.
        except FileNotFoundError: pass
        time.sleep(0.005)
    else: os._exit(126)  # Control: never run user code without assessor release.
'''
