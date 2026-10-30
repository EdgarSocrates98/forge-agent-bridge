"""Runner registry + placement (§7.2, §23.1).

`local` runners are real (the bridge itself). `remote` runners register
with an endpoint and report `unverified` until a real handshake happens —
never claimed live. Placement binds sessions to runner ids in metadata.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from .adapter import BridgeError
from .contracts import utcnow
from .local_bridge import state_dir


class RunnerRegistry:
    KINDS: ClassVar[set[str]] = {"local", "remote"}

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (state_dir() / "runners.json")
        self._ensure_local()

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1))
        self.path.chmod(0o600)

    def _ensure_local(self) -> None:
        data = self._load()
        if "local" not in data:
            data["local"] = {
                "id": "local", "kind": "local", "endpoint": None,
                "state": "ready", "labels": [], "quota_sessions": 8,
                "registered_at": utcnow(),
            }
            self._save(data)

    def register(self, runner_id: str, kind: str, endpoint: str | None = None,
                 labels: list[str] | None = None,
                 quota_sessions: int = 8) -> dict[str, Any]:
        if kind not in self.KINDS:
            raise BridgeError("FAB-VALIDATION", f"unknown runner kind {kind}")
        data = self._load()
        # remote registration is real metadata — liveness stays unverified
        # until health() actually reaches the endpoint.
        data[runner_id] = {
            "id": runner_id, "kind": kind, "endpoint": endpoint,
            "state": "unverified" if kind == "remote" else "ready",
            "labels": labels or [], "quota_sessions": quota_sessions,
            "registered_at": utcnow(),
        }
        self._save(data)
        return dict(data[runner_id])

    def deregister(self, runner_id: str) -> bool:
        if runner_id == "local":
            raise BridgeError("FAB-VALIDATION", "cannot deregister local runner")
        data = self._load()
        if runner_id not in data:
            return False
        data[runner_id]["state"] = "drained"
        self._save(data)
        return True

    def health(self, runner_id: str) -> dict[str, Any]:
        r = self._load().get(runner_id)
        if not r:
            raise BridgeError("FAB-NOT-FOUND", f"unknown runner {runner_id}")
        if r["kind"] == "local":
            return {"id": runner_id, "state": "ready", "detail": "self"}
        # remote: attempt a real TCP/TLS reachability check (urllib, 2s)
        import urllib.request
        ep = str(r.get("endpoint") or "")
        try:
            req = urllib.request.Request(f"{ep.rstrip('/')}/status",
                                         method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                ok = resp.status == 200
            state = "ready" if ok else "unverified"
        except Exception:  # noqa: BLE001 — reachability probe is best-effort
            state = "unverified"
        data = self._load()
        data[runner_id]["state"] = state
        self._save(data)
        return {"id": runner_id, "state": state,
                "detail": "reachable" if state == "ready" else "unreachable"}

    def list(self) -> list[dict[str, Any]]:
        return list(self._load().values())

    def place(self, runner_id: str, *, local_load: int = 0) -> dict[str, Any]:
        """Validate placement: runner exists, ready, quota not exceeded."""
        r = self._load().get(runner_id)
        if not r:
            raise BridgeError("FAB-NOT-FOUND", f"unknown runner {runner_id}")
        if r["kind"] == "remote" and r.get("state") != "ready":
            raise BridgeError("FAB-UNAVAILABLE",
                              "remote runner not verified — run health first")
        if r["kind"] == "local" and local_load >= int(r.get("quota_sessions", 8)):
            raise BridgeError("FAB-QUOTA",
                              f"local runner quota {r['quota_sessions']} reached")
        return dict(r)
