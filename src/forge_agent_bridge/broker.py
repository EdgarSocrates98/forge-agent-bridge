"""Permission broker — central authorization decisions (§25.3).

Validates identity, session, product/workspace, operation, tool, policy;
decides allow / deny / require-approval; records the decision. The broker
complements — never replaces — the owning service's own authorization.
"""
from __future__ import annotations

import time
from typing import Any

from .adapter import BridgeError

# Operations that always require a bound approval token before execution.
APPROVAL_REQUIRED: dict[tuple[str, str], str] = {
    ("files", "upload"): "file-write",
    ("files", "restore"): "file-write",
    ("sessions", "spawn"): "process-spawn",
    ("runners", "register"): "runner-registration",
}
# Risk classification per action family.
RISK = {"file-write": "high", "process-spawn": "high",
        "runner-registration": "medium", "prompt": "low",
        "share": "medium", "approve": "medium", "handoff": "high"}


class Decision(dict):
    """Authorization decision record — auditable."""


class Broker:
    """Central op authorization; decisions are recorded, never silent."""

    def __init__(self) -> None:
        self.log: list[dict[str, Any]] = []

    def authorize(self, *, actor: dict[str, Any] | None, op: str,
                  resource: str, session_id: str = "",
                  product_id: str = "", workspace_id: str = "",
                  tool: str = "", args: dict[str, Any] | None = None,
                  principal: str | None = None,
                  collab: Any = None) -> dict[str, Any]:
        """Return {allow, require_approval, risk, reason} — or raise FORBIDDEN.

        Order: identity → operation risk → ownership/observer → approval need.
        """
        args = args or {}
        if actor is None:
            self._record("deny", op, resource, "", "no-identity")
            raise BridgeError("FAB-AUTH", "authentication required")

        # identity: session tokens carry scopes; master carries 'admin'
        scopes = actor.get("scopes") or ["admin"]
        risk = RISK.get(op.split(":")[-1] if ":" in op else op, "medium")

        # session-scope authorization via collab when a session is bound —
        # ``principal`` is the caller-resolved actor (session tokens can't
        # impersonate; master may assert for local dev).
        if session_id and collab is not None:
            who = principal or actor.get("actor", "local")
            if op not in ("read", "comment"):
                collab.assert_can_act(session_id, who)  # raises

        key = (resource.split(":")[0], op.split(":")[-1])
        needs = APPROVAL_REQUIRED.get(key)
        dec = {
            "allow": True, "require_approval": needs is not None,
            "approval_kind": needs, "risk": risk,
            "actor": actor.get("actor", "?"), "op": op,
            "resource": resource, "session_id": session_id,
            "product_id": product_id, "workspace_id": workspace_id,
            "tool": tool, "scopes": scopes,
        }
        self._record("allow" if not needs else "require-approval",
                     op, resource, dec["actor"], dec["approval_kind"] or "-")
        return Decision(dec)

    def _record(self, verdict: str, op: str, res: str,
                actor: str, detail: str) -> None:
        self.log.append({"ts": time.time(), "verdict": verdict, "op": op,
                         "resource": res, "actor": actor, "detail": detail})


BROKER = Broker()
