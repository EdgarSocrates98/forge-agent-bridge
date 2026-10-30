"""Approval tokens — bound, expiring, single-use authorizations (§25.4).

Replaces client-supplied ``approved: true`` booleans. The server mints an
approval request when a mutating op is attempted; the actor resolves it;
the resolved token's argument digest must match the retried operation
exactly — argument tampering invalidates it. Tokens are one-time.
"""
from __future__ import annotations

import hashlib
import json
import secrets as _secrets
import threading
import time
from typing import Any

from .adapter import BridgeError

TTL_S = 600.0  # 10 min


def digest_args(args: dict[str, Any]) -> str:
    """Stable digest of the operation arguments being approved."""
    canon = json.dumps(args, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


class ApprovalStore:
    """Pending and resolved approvals; resolved grants are one-time."""

    def __init__(self) -> None:
        self._pending: dict[str, dict[str, Any]] = {}
        self._grants: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def request(self, *, session_id: str, actor: str, resource: str,
                action: str, args: dict[str, Any], risk: str = "medium",
                scope: str = "session", turn_id: str = "") -> dict[str, Any]:
        """Create a pending approval bound to op+args digest."""
        ap = {
            "approval_id": f"ap_{_secrets.token_hex(8)}",
            "session_id": session_id, "turn_id": turn_id,
            "actor": actor, "resource": resource, "action": action,
            "args_digest": digest_args(args), "scope": scope, "risk": risk,
            "requested_at": time.time(), "expires_at": time.time() + TTL_S,
            "state": "pending",
        }
        self._pending[ap["approval_id"]] = ap
        return dict(ap)

    def resolve(self, approval_id: str, *, approved: bool,
                actor: str) -> dict[str, Any]:
        with self._lock:
            ap = self._pending.pop(approval_id, None)
            if not ap:
                raise BridgeError("FAB-NOT-FOUND", "unknown approval_id")
            if time.time() > ap["expires_at"]:
                raise BridgeError("FAB-VALIDATION", "approval request expired")
            if not approved:
                return {"resolved": True, "granted": False,
                        "approval_id": approval_id}
            token = _secrets.token_urlsafe(24)
            self._grants[token] = {
                "approval_id": approval_id, "session_id": ap["session_id"],
                "actor": actor, "requester": ap["actor"],
                "resource": ap["resource"], "action": ap["action"],
                "args_digest": ap["args_digest"], "scope": ap["scope"],
                "risk": ap["risk"], "decided_at": time.time(),
                "expires_at": time.time() + TTL_S, "consumed": False,
            }
            return {"resolved": True, "granted": True,
                    "approval_id": approval_id, "approval_token": token,
                    "expires_at": self._grants[token]["expires_at"]}

    def consume(self, token: str, *, session_id: str, resource: str,
                action: str, args: dict[str, Any],
                actor: str | None = None) -> dict[str, Any]:
        """Verify + consume a grant: op must match digest exactly, once.

        Consumption is atomic under the store lock: two simultaneous
        requests cannot both observe ``consumed == False``.
        """
        with self._lock:
            g = self._grants.get(token)
            if not g:
                raise BridgeError("FAB-FORBIDDEN", "invalid approval token")
            if g["consumed"]:
                raise BridgeError("FAB-FORBIDDEN",
                                  "approval token already consumed")
            if time.time() > g["expires_at"]:
                raise BridgeError("FAB-FORBIDDEN", "approval token expired")
            if g["session_id"] != session_id or g["resource"] != resource \
                    or g["action"] != action:
                raise BridgeError("FAB-FORBIDDEN",
                                  "approval token does not cover this operation")
            if g["args_digest"] != digest_args(args):
                raise BridgeError("FAB-FORBIDDEN",
                                  "operation arguments differ from approved")
            if actor is not None and g["requester"] and \
                    actor != g["requester"]:
                raise BridgeError(
                    "FAB-FORBIDDEN",
                    "approval was requested by a different actor")
            g["consumed"] = True
            return {"consumed": True, "approval_id": g["approval_id"],
                    "actor": g["actor"]}

    def pending_for(self, session_id: str) -> list[dict[str, Any]]:
        return [dict(a) for a in self._pending.values()
                if a["session_id"] == session_id]


APPROVALS = ApprovalStore()
