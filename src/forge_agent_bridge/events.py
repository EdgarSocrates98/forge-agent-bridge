"""Event normalization (§5.4–5.5) — envelope, ordering, dedupe, replay."""

from __future__ import annotations

import itertools
from typing import Any

from . import EVENT_SCHEMA
from .contracts import EVENT_TYPES, new_id, utcnow

_seq = itertools.count(1)


def envelope(
    event_type: str,
    provider: str,
    session_id: str,
    payload: dict[str, Any],
    *,
    turn_id: str | None = None,
    provider_version: str | None = None,
    product_id: str | None = None,
    workspace_id: str | None = None,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """forge/AgentBridgeEvent/v1 — unknown types preserved for diagnostics."""
    known = event_type in EVENT_TYPES
    return {
        "schema": EVENT_SCHEMA,
        "id": new_id("evt"),
        "ts": utcnow(),
        "provider": provider,
        "provider_version": provider_version,
        "session_id": session_id,
        "turn_id": turn_id,
        "seq": next(_seq),
        "type": event_type,
        "known_type": known,
        "payload": payload,
        "product_id": product_id,
        "workspace_id": workspace_id,
        "origin": "bridge",
        "raw": raw,  # native event preserved for diagnostics when unmapped
    }


class EventBuffer:
    """Dedupe + ordering + replay window per session."""

    def __init__(self, session_id: str, max_size: int = 5000):
        self.session_id = session_id
        self.max_size = max_size
        self._events: list[dict[str, Any]] = []
        self._seen: set[str] = set()

    def push(self, event: dict[str, Any]) -> bool:
        """True if stored; dedupes on event id, keeps sequence order."""
        eid = event.get("id")
        if eid in self._seen:
            return False
        self._seen.add(eid)
        self._events.append(event)
        self._events.sort(key=lambda e: e.get("seq", 0))
        if len(self._events) > self.max_size:
            dropped = self._events.pop(0)
            self._seen.discard(dropped.get("id"))
        return True

    def replay(self, after_seq: int = 0) -> list[dict[str, Any]]:
        return [e for e in self._events if e.get("seq", 0) > after_seq]

    def __len__(self) -> int:
        return len(self._events)


# Minimal native→normalized mapping seeds. Providers extend per-adapter.
NATIVE_MAP: dict[str, str] = {
    "session/new": "session.created",
    "session/resume": "session.resumed",
    "session/close": "session.closed",
    "prompt": "turn.started",
    "content_delta": "message.delta",
    "content": "message.completed",
    "tool_call": "tool.started",
    "tool_result": "tool.completed",
    "request_permission": "approval.requested",
    "permission_response": "approval.resolved",
    "usage": "usage.updated",
    "error": "runtime.error",
}


def normalize(native: dict[str, Any], provider: str, session_id: str) -> dict[str, Any]:
    """Map a provider-native event to the v1 envelope. Unknown native types
    are preserved under `raw` with type `runtime.unknown` — never dropped."""
    ntype = str(native.get("type") or native.get("method") or "unknown")
    mapped = NATIVE_MAP.get(ntype)
    if mapped:
        return envelope(mapped, provider, session_id,
                        native.get("payload") or native.get("params") or {},
                        raw=native)
    return envelope("runtime.error", provider, session_id,
                    {"reason": "unmapped-native-event", "native_type": ntype},
                    raw=native)
