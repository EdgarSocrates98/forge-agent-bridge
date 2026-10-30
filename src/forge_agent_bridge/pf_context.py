"""Cycle 30.2 — Product Forge context authorization client (§5.3/§5.4).

Server-side re-verification: when a session binds a product_id the
Bridge asks Product Forge to *issue* a
``forge/ProductAgentSessionContext/v2`` — product/workspace existence
and principal scope are validated there, never trusted from the client.
At prompt time the issued ``server_ref`` is re-checked (state
active|expired|revoked) with a short TTL cache.

Config (env):
  FAB_PF_BASE_URL   e.g. http://127.0.0.1:8470 — unset → unverified mode
  FAB_PF_TOKEN      bearer token for the PF API
  FAB_PF_VERIFY     required|best-effort|off (default best-effort)

Honest states: a bound context without a verified server_ref is marked
``pf_verify: unverified``; ``required`` mode fails closed with
FAB-UNAVAILABLE instead of silently trusting the binding.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from .adapter import BridgeError


class PFContextClient:
    def __init__(self, base_url: str, token: str, timeout: float = 5.0,
                 check_ttl_s: float | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        if check_ttl_s is None:
            check_ttl_s = float(
                os.environ.get("FAB_PF_CHECK_TTL", "30") or 30)
        self.check_ttl_s = check_ttl_s
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    @classmethod
    def from_env(cls) -> PFContextClient | None:
        url = os.environ.get("FAB_PF_BASE_URL", "").strip()
        tok = os.environ.get("FAB_PF_TOKEN", "").strip()
        if not url or not tok:
            return None
        return cls(url, tok)

    @staticmethod
    def mode() -> str:
        return os.environ.get("FAB_PF_VERIFY", "best-effort").strip() or \
            "best-effort"

    def _req(self, method: str, path: str,
             body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(
            f"{self.base_url}{path}", data=data, method=method,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(r, timeout=self.timeout) as resp:
                env = json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                env = json.loads(e.read() or b"{}")
            except ValueError:
                env = {"error": {"code": "PF-HTTP", "message": str(e)}}
            err = env.get("error") or {}
            raise PFHttpError(e.code,
                              str(err.get("code", "PF-ERROR")),
                              str(err.get("message", e))) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise PFUnreachable(str(e)) from e
        if "error" in env:
            err = env["error"]
            raise PFHttpError(0, str(err.get("code", "PF-ERROR")),
                              str(err.get("message", "pf error")))
        return env.get("data") or {}

    def authorize(self, *, principal: str, product_id: str,
                  workspace_id: str | None, session_id: str,
                  provider: str, agent_profile: str,
                  ttl_s: int = 3600) -> dict[str, Any]:
        return self._req("POST", "/api/v1/context/authorize", {
            "principal": principal, "product_id": product_id,
            "workspace_id": workspace_id, "session_id": session_id,
            "provider": provider, "agent_profile": agent_profile,
            "ttl_s": ttl_s})

    def check(self, ctx_id: str, *, force: bool = False) -> dict[str, Any]:
        """Prompt-time re-verification: returns the PF record incl.
        ``state`` (active|expired|revoked). Cached CHECK_TTL_S."""
        now = time.time()
        hit = self._cache.get(ctx_id)
        if hit and not force and now - hit[0] < self.check_ttl_s:
            return hit[1]
        rec = self._req("GET", f"/api/v1/context/{ctx_id}")
        self._cache[ctx_id] = (now, rec)
        return rec

    def revoke(self, ctx_id: str) -> dict[str, Any]:
        self._cache.pop(ctx_id, None)
        return self._req("POST", f"/api/v1/context/{ctx_id}/revoke")

    def invalidate(self, ctx_id: str) -> None:
        self._cache.pop(ctx_id, None)


class PFUnreachable(BridgeError):
    def __init__(self, msg: str):
        super().__init__("FAB-UNAVAILABLE",
                         f"product-forge unreachable: {msg}")


class PFHttpError(BridgeError):
    def __init__(self, status: int, code: str, msg: str):
        super().__init__(f"FAB-PF-{code}", msg)
        self.status = status
