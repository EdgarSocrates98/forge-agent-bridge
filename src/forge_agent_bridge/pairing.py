"""Secure pairing — session tokens, devices, rotation, revocation (§25.6).

The master pair token (``~/.forge-bridge/pair.token``) stays a local file
secret — clients exchange it once for a **scoped, expiring session token**;
the master token is never required in browser storage.

Tokens are stored hashed; revocation and expiry are enforced server-side.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets as _secrets
import threading
import time
from pathlib import Path
from typing import Any

from .adapter import BridgeError

SESSION_TTL_S = 8 * 3600.0


def _hash(tok: str) -> str:
    return hashlib.sha256(("fab-tok:" + tok).encode()).hexdigest()


class Pairing:
    """Exchange master token → device-bound session token."""

    def __init__(self, master_token: str, path: Path | None = None) -> None:
        self._master = master_token  # kept only for verify+rotate
        self._master_hash = _hash(master_token)
        self._sessions: dict[str, dict[str, Any]] = {}  # hash -> device session
        self._revoked: set[str] = set()
        self._path = path
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if self._path is None:
            return
        try:
            doc = json.loads(self._path.read_text(encoding="utf-8"))
            if h := doc.get("master_hash"):
                self._master_hash = str(h)
            self._sessions = dict(doc.get("sessions") or {})
            self._revoked = set(doc.get("revoked") or [])
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"schema": "forge/PairingState/1", "master_hash": self._master_hash,
               "sessions": self._sessions, "revoked": sorted(self._revoked)}
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self._path)

    # -- master token ----------------------------------------------------
    def verify(self, token: str) -> bool:
        return hmac.compare_digest(_hash(token), self._master_hash)

    def rotate(self, presented: str) -> dict[str, Any]:
        """Rotate the master pair token (requires the current master)."""
        with self._lock:
            if not self.verify(presented):
                raise BridgeError("FAB-FORBIDDEN", "invalid pair token")
            new = _secrets.token_urlsafe(32)
            self._master, self._master_hash = new, _hash(new)
            self._save()
            # all session tokens stay valid until their own expiry
            return {"rotated": True, "pair_token": new}

    # -- pairing exchange -------------------------------------------------
    def exchange(self, presented: str, device_name: str,
                 scopes: tuple[str, ...] = ("agent",)) -> dict[str, Any]:
        """Master token → scoped session token (device registered)."""
        with self._lock:
            if not self.verify(presented):
                raise BridgeError("FAB-FORBIDDEN", "invalid pair token")
            tok = _secrets.token_urlsafe(32)
            device = {
                "device_id": f"dev_{_secrets.token_hex(6)}",
                "device_name": device_name or "unnamed",
                "scopes": list(scopes),
                "created_at": time.time(),
                "expires_at": time.time() + SESSION_TTL_S,
                "last_seen": time.time(),
            }
            self._sessions[_hash(tok)] = device
            self._save()
            return {"session_token": tok, "device": device}

    def principal(self, token: str) -> dict[str, Any] | None:
        """Resolve a session token → device record (None = not a session)."""
        with self._lock:
            d = self._sessions.get(_hash(token))
        if not d or _hash(token) in self._revoked:
            return None
        if time.time() > d["expires_at"]:
            return None
        d["last_seen"] = time.time()
        return d

    def authenticate(self, token: str) -> dict[str, Any]:
        """Accept master OR valid session token → auth record."""
        if self.verify(token):
            return {"kind": "master", "actor": "local"}
        d = self.principal(token)
        if d:
            return {"kind": "session", "actor": d["device_name"],
                    "device_id": d["device_id"], "scopes": d["scopes"]}
        raise BridgeError("FAB-AUTH", "invalid or expired token")

    # -- devices ----------------------------------------------------------
    def devices(self) -> list[dict[str, Any]]:
        out = []
        for h, d in self._sessions.items():
            if h in self._revoked:
                continue
            out.append({k: v for k, v in d.items()})
        return out

    def revoke_device(self, device_id: str) -> bool:
        with self._lock:
            for h, d in self._sessions.items():
                if d["device_id"] == device_id:
                    self._revoked.add(h)
                    self._save()
                    return True
        return False

    def revoke_all(self) -> int:
        with self._lock:
            n = len(self._sessions)
            self._revoked.update(self._sessions)
            self._save()
            return n
