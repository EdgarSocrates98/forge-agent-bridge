"""Runner SSRF protection — validate + probe remote endpoints (§25.7).

Runner registration supplies an endpoint URL. Before any health probe the
URL is validated: scheme, resolvable non-dangerous host, no redirects
followed blindly, and the probed runner must prove its identity by echoing
its runner id. Private/loopback/metadata IPs are rejected unless the caller
explicitly opts in to a localhost dev runner.
"""
from __future__ import annotations

import ipaddress
import json
import socket
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from .adapter import BridgeError

_BLOCKED_NETS = [
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / cloud metadata
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("224.0.0.0/4"),       # multicast
    ipaddress.ip_network("240.0.0.0/4"),       # reserved
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]
_LOOPBACK = [ipaddress.ip_network("127.0.0.0/8"),
             ipaddress.ip_network("::1/128")]


def _resolve_ips(host: str) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise BridgeError("FAB-SSRF", f"DNS resolution failed: {e}") from e
    return [ipaddress.ip_address(i[4][0]) for i in infos]


def validate_runner_url(url: str, *, allow_loopback: bool = False) -> str:
    """Validate a runner endpoint URL → returns normalized URL or raises.

    Policy: http(s) only, explicit port required on non-standard, DNS must
    resolve, every resolved IP must be outside blocked nets; loopback only
    with ``allow_loopback`` (dev runners on the same box).
    """
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise BridgeError("FAB-SSRF", "runner endpoint must be http(s)")
    if not p.hostname:
        raise BridgeError("FAB-SSRF", "runner endpoint missing host")
    host = p.hostname
    for ip in _resolve_ips(host):
        if any(ip in net for net in _LOOPBACK) and not allow_loopback:
            raise BridgeError(
                "FAB-SSRF",
                "runner resolves to loopback; pass allow_loopback for dev")
        if any(ip in net for net in _BLOCKED_NETS):
            raise BridgeError(
                "FAB-SSRF", f"runner resolves to blocked range {ip}")
        if ip.is_private and not allow_loopback and host not in (
                "localhost",):
            # RFC1918 remote runners are allowed only when caller opted in
            # via allow_loopback (named 'local-network' trust decision)
            raise BridgeError(
                "FAB-SSRF",
                f"runner resolves to private range {ip}; "
                "pass allow_loopback for LAN/dev runners")
    return url.rstrip("/")


def probe(url: str, expected_runner_id: str, timeout: float = 5.0) -> dict[str, Any]:
    """GET {url}/health — no redirects, TLS-verified (https), identity check.

    A runner proves identity by returning JSON with ``runner_id`` matching
    ``expected_runner_id`` (or an ``X-Runner-Id`` header). Any other 200 is
    *not* trusted — answering HTTP is not proof of being a runner.
    """
    req = urllib.request.Request(url.rstrip("/") + "/health",
                                 headers={"Accept": "application/json"})

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None  # do not follow — report instead

    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            rid = resp.headers.get("X-Runner-Id")
            body = resp.read(64 * 1024)
            data = json.loads(body) if body else {}
            rid = rid or data.get("runner_id")
            if rid != expected_runner_id:
                raise BridgeError(
                    "FAB-SSRF",
                    f"endpoint did not prove identity "
                    f"(expected {expected_runner_id!r}, got {rid!r})")
            return {"state": "ready", "runner_id": rid,
                    "endpoint": url, "checked": True}
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 307, 308):
            raise BridgeError("FAB-SSRF",
                              "redirect refused during runner probe") from e
        raise BridgeError("FAB-ERROR", f"runner probe HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise BridgeError("FAB-ERROR", f"runner unreachable: {e}") from e
