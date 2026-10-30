"""Cycle 28.2 — Session Recovery Plans.

`forge/SessionRecoveryPlan/v1` states exactly how a session can come back —
honestly, per provider mechanism and persisted state:

  native-resume      provider exposes a real resume handle (session_ref)
  context-rebuild    no native handle — new session seeded with replay
  read-only-history  events preserved; provider handle gone — view only
  non-resumable      neither a provider handle nor durable events exist
"""

from __future__ import annotations

from typing import Any

RECOVERY_SCHEMA = "forge/SessionRecoveryPlan/v1"


def plan_for(session: dict[str, Any], *, provider_resumable: bool,
             events_count: int, context_version: int | None = None
             ) -> dict[str, Any]:
    ref = session.get("provider_session_ref")
    live = session.get("state") not in ("closed", "failed")
    if live and provider_resumable and ref:
        mode, steps = "native-resume", [
            "call provider resume with provider_session_ref",
            "replay events after last delivered seq"]
    elif events_count:
        mode, steps = ("context-rebuild" if live else "read-only-history"), [
            "replay persisted events to rebuild timeline",
            ("re-attach ProductAgentSessionContext "
            f"v{context_version or '?'}"),
            "resume provider via context injection (not native)"]
    else:
        mode, steps = "non-resumable", ["no provider ref and no event history"]
    return {"schema": RECOVERY_SCHEMA, "session_id": session.get("id"),
            "mode": mode, "native_resumable": bool(live and ref),
            "provider_session_ref": ref,
            "events_persisted": events_count,
            "context_version": context_version,
            "continuity": ("native" if mode == "native-resume"
                           else "reconstructed" if events_count
                           else "none"),
            "steps": steps}
