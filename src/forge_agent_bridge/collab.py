"""Collaboration primitives (§23.2) — sharing, observers, comments, audit.

The bridge is a single-user localhost service; collaboration records are
real, persisted state that the Portal and remote runners consume.
Principals arrive via `X-FAB-Principal` header. Observers are read-only —
enforced at the route layer (cannot prompt/approve/delete).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .adapter import BridgeError
from .contracts import utcnow
from .local_bridge import state_dir


class AuditLog:
    """Append-only JSONL audit trail for mutating collab actions."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (state_dir() / "audit.jsonl")

    def emit(self, action: str, principal: str, **fields: Any) -> dict[str, Any]:
        rec = {"ts": utcnow(), "action": action, "principal": principal,
               **fields}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        self.path.chmod(0o600)
        return rec

    def tail(self, n: int = 50) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text().strip().splitlines()
        except OSError:
            return []
        return [json.loads(l) for l in lines[-n:]]


class CollabStore:
    """Per-session sharing records: owner, visibility, observers,
    delegated approver, comments."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (state_dir() / "collab.json")

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1))
        self.path.chmod(0o600)

    def rec(self, sid: str) -> dict[str, Any]:
        return dict(self._load().get(sid) or {
            "owner": "local", "visibility": "private",
            "observers": [], "delegated_to": None, "comments": []})

    def _put(self, sid: str, rec: dict[str, Any]) -> dict[str, Any]:
        data = self._load()
        rec["updated_at"] = utcnow()
        data[sid] = rec
        self._save(data)
        return dict(rec)

    def share(self, sid: str, *, owner: str, visibility: str,
              observers: list[str] | None = None,
              delegated_to: str | None = None) -> dict[str, Any]:
        if visibility not in ("private", "workspace", "team"):
            raise BridgeError("FAB-VALIDATION",
                              "visibility must be private|workspace|team")
        rec = self.rec(sid)
        rec.update(owner=owner, visibility=visibility,
                   observers=observers or rec["observers"],
                   delegated_to=delegated_to)
        return self._put(sid, rec)

    def comment(self, sid: str, author: str, text: str) -> dict[str, Any]:
        rec = self.rec(sid)
        rec["comments"].append(
            {"ts": utcnow(), "author": author, "text": text[:2000]})
        return self._put(sid, rec)

    # -- authorization --------------------------------------------------------

    def principal(self, sid: str, header_principal: str | None) -> str:
        """Effective principal: header wins, else session owner."""
        return header_principal or self.rec(sid)["owner"]

    def assert_can_act(self, sid: str, principal: str) -> None:
        """Observers are read-only — they cannot prompt/approve/delete."""
        rec = self.rec(sid)
        if principal == rec["owner"]:
            return
        if rec["visibility"] == "private":
            raise BridgeError(
                "FAB-FORBIDDEN",
                f"session {sid} is private to '{rec['owner']}'")
        if principal in rec["observers"]:
            raise BridgeError(
                "FAB-FORBIDDEN",
                f"observer '{principal}' is read-only on session {sid}")
        # shared visibility + unknown principal → treat as observer
        raise BridgeError(
            "FAB-FORBIDDEN",
            f"principal '{principal}' has no write grant on {sid}")

    def assert_can_approve(self, sid: str, principal: str) -> None:
        rec = self.rec(sid)
        if principal in (rec["owner"], rec["delegated_to"]):
            return
        raise BridgeError(
            "FAB-FORBIDDEN",
            f"'{principal}' cannot approve on session {sid}")
