"""Session orchestrator — the Bridge service surface the Portal consumes.

Composes adapter + normalization + event buffer into one API:
create session → prompt → drain events → replay → cancel → close.

Cycle 28: a `DurableEventStore` shadows every push to JSONL, so replay
survives a bridge restart; the in-memory buffer remains the hot path.
"""

from __future__ import annotations

from typing import Any

from .adapter import BridgeError, ProviderAdapter
from .contracts import AgentSession
from .events import DurableEventStore, EventBuffer, normalize


class BridgeOrchestrator:
    def __init__(self, adapter: ProviderAdapter, provider_id: str,
                 store: DurableEventStore | None = None) -> None:
        self.adapter, self.provider_id = adapter, provider_id
        self.sessions: dict[str, AgentSession] = {}
        self.buffers: dict[str, EventBuffer] = {}
        self.store = store

    def create_session(self, **kw: Any) -> AgentSession:
        s = self.adapter.create_session(**kw)
        self.sessions[s.id] = s
        self.buffers[s.id] = EventBuffer(s.id)
        self._push(s.id, {"type": "session/new", "params": {"session_id": s.id}})
        return s

    def prompt(self, session_id: str, text: str,
               attachments: list[dict[str, Any]] | None = None) -> None:
        self._require(session_id)
        self._push(session_id, {"type": "prompt", "params": {
            "text": text,
            "attachments": len(attachments or [])}})
        self.adapter.send_prompt(session_id, text, attachments=attachments)

    def drain(self, session_id: str) -> int:
        """Pull native events → normalize → buffer. Returns count stored."""
        self._require(session_id)
        n = 0
        for native in self.adapter.stream_events(session_id):
            if self._push(session_id, native):
                n += 1
        return n

    def replay(self, session_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        if session_id in self.buffers:
            return self.buffers[session_id].replay(after_seq)
        if self.store and self.store.replay(session_id):
            return self.store.replay(session_id, after_seq)   # cold restart
        self._require(session_id)
        return []

    def list_sessions(self) -> list[AgentSession]:
        return self.adapter.list_sessions()

    def resume(self, session_ref: str) -> AgentSession:
        s = self.adapter.resume_session(session_ref)
        self.sessions[s.id] = s
        self.buffers[s.id] = EventBuffer(s.id)
        self._push(s.id, {"type": "session/resume",
                          "params": {"session_id": s.id, "ref": session_ref}})
        return s

    def artifacts(self, session_id: str) -> list[dict[str, Any]]:
        """Artifacts derived from buffered events (§22.1) — real data."""
        self._require(session_id)
        out: list[dict[str, Any]] = []
        for e in self.buffers[session_id].replay():
            if e["type"].startswith("artifact."):
                out.append({"event_id": e["id"], "type": e["type"],
                            "seq": e["seq"], **e["payload"]})
            elif e["type"] == "tool.completed" and e["payload"].get("path"):
                out.append({"event_id": e["id"], "type": "tool.output",
                            "seq": e["seq"], "path": e["payload"]["path"]})
        return out

    def approve(self, session_id: str, approval_id: str, approved: bool) -> None:
        self._require(session_id)
        self.adapter.respond_to_approval(approval_id, approved)
        self._push(session_id, {"type": "permission_response",
                                "params": {"approval_id": approval_id,
                                           "approved": approved}})

    def cancel(self, session_id: str) -> None:
        self.adapter.cancel(session_id)
        self._push(session_id, {"type": "session/cancel",
                                "params": {"session_id": session_id}})

    def close(self, session_id: str) -> None:
        self.adapter.close_session(session_id)
        self._push(session_id, {"type": "session/close",
                                "params": {"session_id": session_id}})

    def _push(self, session_id: str, native: dict[str, Any]) -> bool:
        ev = normalize(native, self.provider_id, session_id)
        ok = self.buffers[session_id].push(ev)
        if ok and self.store:
            self.store.append(ev)      # durable shadow — survives restart
        return ok

    def _require(self, session_id: str) -> None:
        if session_id not in self.sessions:
            raise BridgeError("FAB-SESSION", f"unknown session {session_id}")


def build_orchestrator(provider_id: str,
                       store: DurableEventStore | None = None
                       ) -> BridgeOrchestrator:
    """Resolve an adapter for the provider. `fake` works anywhere;
    real providers resolve via registry-installed adapters."""
    from .registry import REGISTRY
    if provider_id == "fake":
        from .providers.fake import FakeAdapter
        return BridgeOrchestrator(FakeAdapter(), provider_id, store=store)
    adapter = REGISTRY.adapter(provider_id)
    if not adapter:
        raise BridgeError("FAB-UNAVAILABLE",
                          f"no adapter registered for '{provider_id}' — "
                          "install/configure the provider first")
    return BridgeOrchestrator(adapter, provider_id, store=store)
