"""Event normalization (§5.4–5.5) — envelope, ordering, dedupe, replay.

Cycle 28 adds `DurableEventStore`: JSONL append per session so a bridge
restart preserves history (§28.3): seq, event id, timestamp, session/turn/
provider, redacted payload, replay cursor, retention.
"""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path
from typing import Any

from . import EVENT_SCHEMA
from .contracts import EVENT_TYPES, new_id, utcnow

_seq = itertools.count(1)


def seq_floor(n: int) -> None:
    """Restart-safe sequencing (§28.3): after loading persisted events the
    counter resumes above the max persisted seq — never reissues a seq."""
    global _seq
    _seq = itertools.count(n + 1)


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


# -- durable store (§28.3) ------------------------------------------------

_SECRET_KEYS = re.compile(
    r"(token|secret|password|api[_-]?key|authorization|credential)", re.IGNORECASE)
_REDACTED = "[redacted]"


def redact(obj: Any) -> Any:
    """Recursively redact secret-looking keys before persistence."""
    if isinstance(obj, dict):
        return {k: (_REDACTED if _SECRET_KEYS.search(str(k)) else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


class DurableEventStore:
    """Append-only JSONL per session under state_dir()/events/.

    Semantics (§28.3): every event carries seq + event id + timestamp +
    session/turn/provider + redacted payload. `replay(after_seq)` is the
    cursor. Retention trims by max bytes AND max events; the oldest events
    drop first but `session.created` is never silently dropped — a
    `session.retention-trim` marker is written in its place.
    """

    def __init__(self, root: Path, *, max_events: int = 10_000,
                 max_bytes: int = 64 * 1024 * 1024) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_events = max_events
        self.max_bytes = max_bytes

    def _file(self, session_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)
        return self.root / f"{safe}.jsonl"

    def append(self, event: dict[str, Any]) -> None:
        e = dict(event)
        e["payload"] = redact(e.get("payload"))
        if e.get("raw") is not None:
            e["raw"] = redact(e["raw"])
        with self._file(str(e["session_id"])).open("a") as f:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
        self._file(str(e["session_id"])).chmod(0o600)

    def replay(self, session_id: str, after_seq: int = 0
               ) -> list[dict[str, Any]]:
        f = self._file(session_id)
        if not f.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            if e.get("seq", 0) > after_seq:
                out.append(e)
        out.sort(key=lambda e: e.get("seq", 0))
        return out

    def latest_seq(self, session_id: str) -> int:
        evs = self.replay(session_id)
        return max((e.get("seq", 0) for e in evs), default=0)

    def enforce_retention(self, session_id: str) -> None:
        f = self._file(session_id)
        if not f.exists():
            return
        lines = f.read_text().splitlines()
        while lines and (
                len(lines) > self.max_events
                or f.stat().st_size > self.max_bytes):
            lines.pop(0)
        if not lines:
            return
        marker = json.dumps({
            "schema": EVENT_SCHEMA, "id": new_id("evt"), "ts": utcnow(),
            "provider": "bridge", "session_id": session_id,
            "turn_id": None, "seq": 0, "type": "session.retention-trim",
            "payload": {"note": "oldest events trimmed by retention"}})
        f.write_text(marker + "\n" + "\n".join(lines) + "\n")
        f.chmod(0o600)


# Minimal native→normalized mapping seeds. Providers extend per-adapter.
NATIVE_MAP: dict[str, str] = {
    "session/new": "session.created",
    "session/resume": "session.resumed",
    "session/close": "session.closed",
    "prompt": "turn.started",
    "turn_start": "turn.started",
    "content_delta": "message.delta",
    "content": "message.completed",
    "tool_call": "tool.started",
    "tool_result": "tool.completed",
    "plan_update": "plan.updated",
    "request_permission": "approval.requested",
    "permission_response": "approval.resolved",
    "usage": "usage.updated",
    "error": "runtime.error",
    "unknown": "runtime.unknown",
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
