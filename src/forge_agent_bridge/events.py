"""Event normalization (§5.4–5.5) — envelope, ordering, dedupe, replay.

Cycle 28 adds `DurableEventStore`: JSONL append per session so a bridge
restart preserves history (§28.3): seq, event id, timestamp, session/turn/
provider, redacted payload, replay cursor, retention.
"""

from __future__ import annotations

import itertools
import json
import re
import threading
from pathlib import Path
from typing import Any

from . import EVENT_SCHEMA
from .contracts import EVENT_TYPES, new_id, utcnow

_seq = itertools.count(1)
_seq_lock = threading.Lock()


def seq_floor(n: int) -> None:
    """Restart-safe sequencing (§28.3): after loading persisted events the
    counter resumes above the max persisted seq — never reissues a seq."""
    global _seq
    with _seq_lock:
        _seq = itertools.count(n + 1)


def _next_seq() -> int:
    with _seq_lock:
        return next(_seq)


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
        "seq": _next_seq(),
        "type": event_type,
        "known_type": known,
        "payload": redact(payload),
        "product_id": product_id,
        "workspace_id": workspace_id,
        "origin": "bridge",
        # Native data remains available for diagnostics, but never carries a
        # credential into an in-memory consumer such as Portal or Lens.
        "raw": redact(raw) if raw is not None else None,
    }


class EventBuffer:
    """Dedupe + ordering + replay window per session."""

    def __init__(self, session_id: str, max_size: int = 5000):
        self.session_id = session_id
        self.max_size = max_size
        self._events: list[dict[str, Any]] = []
        self._seen: set[str] = set()
        self._lock = threading.RLock()

    def push(self, event: dict[str, Any]) -> bool:
        """True if stored; dedupes on event id, keeps sequence order."""
        with self._lock:
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
        with self._lock:
            return [e for e in self._events if e.get("seq", 0) > after_seq]

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)


# -- durable store (§28.3) ------------------------------------------------

_SECRET_KEYS = re.compile(
    r"(?:^|[_-])(token|secret|password|api[_-]?key|authorization|credential)(?:$|[_-])",
    re.IGNORECASE,
)
_REDACTED = "[redacted]"
_SECRET_ASSIGNMENT = re.compile(
    r"(\b(?:access[_-]?token|token|secret|password|api[_-]?key|"
    r"authorization|credential)\b\s*[:=]\s*(?:Bearer\s+)?)"
    r"([^\s,;&]+)", re.IGNORECASE)
_BEARER = re.compile(r"(\bBearer\s+)([^\s,;&]+)", re.IGNORECASE)
_KNOWN_TOKEN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]+|gh[pousr]_[A-Za-z0-9_-]+|xox[baprs]-[A-Za-z0-9-]+)\b")
_URL_CREDENTIAL = re.compile(r"(://[^:/?#\s]+:)([^@/\s]+)(@)")


def redact(obj: Any) -> Any:
    """Recursively redact secret-looking keys and values.

    Key-based redaction handles structured provider payloads; the bounded
    value patterns cover diagnostics that arrive as free text or URLs.  The
    replacement preserves the surrounding field name and shape so operators
    can still identify the failed operation without retaining its secret.
    """
    if isinstance(obj, dict):
        return {k: (_REDACTED if _SECRET_KEYS.search(str(k)) else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        value = _SECRET_ASSIGNMENT.sub(r"\1" + _REDACTED, obj)
        value = _BEARER.sub(r"\1" + _REDACTED, value)
        value = _KNOWN_TOKEN.sub(_REDACTED, value)
        return _URL_CREDENTIAL.sub(r"\1" + _REDACTED + r"\3", value)
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
        if max_events < 1:
            raise ValueError("max_events must be at least 1")
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_events = max_events
        self.max_bytes = max_bytes
        self._lock = threading.RLock()

    def _file(self, session_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)
        return self.root / f"{safe}.jsonl"

    def append(self, event: dict[str, Any]) -> None:
        with self._lock:
            e = dict(event)
            e["payload"] = redact(e.get("payload"))
            if e.get("raw") is not None:
                e["raw"] = redact(e["raw"])
            path = self._file(str(e["session_id"]))
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(e, separators=(",", ":")) + "\n")
            try:
                path.chmod(0o600)
            except OSError:
                pass
            self._enforce_retention_locked(path, str(e["session_id"]))

    def replay(self, session_id: str, after_seq: int = 0
               ) -> list[dict[str, Any]]:
        with self._lock:
            f = self._file(session_id)
            if not f.exists():
                return []
            out: list[dict[str, Any]] = []
            for line in f.read_text(encoding="utf-8").splitlines():
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
        with self._lock:
            f = self._file(session_id)
            if not f.exists():
                return
            self._enforce_retention_locked(f, session_id)

    def _enforce_retention_locked(self, path: Path, session_id: str) -> None:
        """Apply retention while the store lock is held.

        A trim marker is metadata and counts toward both configured limits.
        Once a session has been trimmed, one marker is retained and the
        event budget becomes ``max_events - 1``.  Malformed JSONL is surfaced
        instead of being silently discarded.
        """
        raw_lines = path.read_text(encoding="utf-8").splitlines()
        if not raw_lines:
            return
        entries: list[tuple[str, dict[str, Any]]] = []
        for line_number, line in enumerate(raw_lines, start=1):
            try:
                entries.append((line, json.loads(line)))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"malformed event JSONL at {path}:{line_number}") from exc

        marker_lines = [line for line, entry in entries
                        if entry.get("type") == "session.retention-trim"]
        event_lines = [line for line, entry in entries
                       if entry.get("type") != "session.retention-trim"]
        marker = marker_lines[0] if marker_lines else None

        def size(lines: list[str], marker_line: str | None) -> int:
            total = sum(len(line.encode("utf-8")) + 1 for line in lines)
            if marker_line is not None:
                total += len(marker_line.encode("utf-8")) + 1
            return total

        already_within_limits = (
            len(event_lines) + (1 if marker is not None else 0)
            <= self.max_events
            and size(event_lines, marker) <= self.max_bytes
        )
        if already_within_limits and len(marker_lines) <= 1:
            return

        if marker is None:
            marker = json.dumps({
                "schema": EVENT_SCHEMA, "id": new_id("evt"), "ts": utcnow(),
                "provider": "bridge", "session_id": session_id,
                "turn_id": None, "seq": 0, "type": "session.retention-trim",
                "payload": {"note": "oldest events trimmed by retention"}},
                separators=(",", ":"))

        while event_lines and (
                len(event_lines) + 1 > self.max_events
                or size(event_lines, marker) > self.max_bytes):
            event_lines.pop(0)

        if size(event_lines, marker) > self.max_bytes:
            raise ValueError(
                "max_bytes is too small to persist the retention marker")

        content = marker + "\n"
        if event_lines:
            content += "\n".join(event_lines) + "\n"
        path.write_text(content, encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass


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
    "turn_complete": "turn.completed",
    "request_permission": "approval.requested",
    "permission_response": "approval.resolved",
    "usage": "usage.updated",
    "error": "runtime.error",
    "unknown": "runtime.unknown",
}


def normalize(native: dict[str, Any], provider: str, session_id: str) -> dict[str, Any]:
    """Map a provider-native event to the v1 envelope.

    An unmapped provider event is diagnostic information, not evidence that
    the provider failed.  Keep real provider ``error`` events as
    ``runtime.error`` while classifying unknown, malformed, or newly-added
    native shapes as ``runtime.unknown`` and preserving them under ``raw``.
    """
    raw_type = native.get("type")
    if raw_type is None:
        raw_type = native.get("method")
    if not isinstance(raw_type, str) or not raw_type:
        ntype = ("unknown" if raw_type is None or raw_type == ""
                 else f"<non-text:{type(raw_type).__name__}>")
    else:
        ntype = raw_type

    mapped = NATIVE_MAP.get(ntype)
    native_payload = native.get("payload")
    if native_payload is None:
        native_payload = native.get("params")
    payload = (native_payload if isinstance(native_payload, dict)
               else ({"native_payload": native_payload}
                     if native_payload is not None else {}))
    if mapped:
        return envelope(mapped, provider, session_id, payload, raw=native)
    return envelope("runtime.unknown", provider, session_id,
                    {"reason": "unmapped-native-event", "native_type": ntype,
                     "payload_shape": type(native_payload).__name__
                     if native_payload is not None else None},
                    raw=native)
