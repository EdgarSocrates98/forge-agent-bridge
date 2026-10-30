"""Cycle 30.1 §11.3 — Session Integrity Checker.

Deterministic, read-only checks over session state. Every finding carries a
named check id; absence of findings means "no check detected a problem",
never "the session is provably correct".
"""

from __future__ import annotations

import os
from typing import Any

from .contracts import new_id, utcnow

SCHEMA = "forge/SessionIntegrity/v1"


def _proc_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def check_session(sid: str, *, events: list[dict[str, Any]],
                  meta: dict[str, Any] | None,
                  pending_approvals: list[dict[str, Any]],
                  known_providers: set[str]) -> dict[str, Any]:
    """Run all integrity checks for one session."""
    findings: list[dict[str, Any]] = []

    def flag(check: str, severity: str, detail: str) -> None:
        findings.append({"check": check, "severity": severity,
                         "detail": detail})

    # missing events: gaps in the monotonic seq
    seqs = sorted(e["seq"] for e in events if isinstance(e.get("seq"), int))
    if seqs:
        missing = sorted(set(range(seqs[0], seqs[-1] + 1)) - set(seqs))
        if missing:
            flag("missing-events", "high",
                 f"seq gaps at {missing[:10]}"
                 + ("…" if len(missing) > 10 else ""))

    # duplicate events: same event id twice
    ids = [e.get("id") for e in events if e.get("id")]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        flag("duplicate-events", "high", f"ids repeated: {dup[:10]}")

    # invalid cursor: largest seq beyond the store's high-water mark is
    # an upstream concern; here a cursor embedded in replay events that
    # points backwards is invalid.
    cursors = [e.get("cursor") for e in events
               if isinstance(e.get("cursor"), int)]
    for e, c in zip((e for e in events if isinstance(e.get("cursor"), int)),
                    cursors, strict=False):
        if c > e.get("seq", -1):
            flag("invalid-cursor", "medium",
                 f"cursor {c} ahead of seq {e.get('seq')}")
            break

    # orphan processes: recorded runner pid no longer alive
    for e in events:
        pid = (e.get("payload") or {}).get("pid")
        if isinstance(pid, int) and not _proc_alive(pid):
            flag("orphan-process", "medium",
                 f"recorded pid {pid} is not alive")
            break

    # expired approvals still pending
    import time
    now = time.time()
    for ap in pending_approvals:
        if ap.get("expires_at") and ap["expires_at"] < now:
            flag("expired-approval", "low",
                 f"pending approval {ap.get('approval_id')} expired")
            break

    # broken provider references
    provider = (meta or {}).get("provider") or ""
    if provider and provider not in known_providers:
        flag("broken-provider-ref", "high",
             f"provider '{provider}' not in registry")

    # missing artifacts: artifact events referencing absent files
    for e in events:
        if e.get("type") == "artifact.created":
            p = (e.get("payload") or {}).get("path")
            if p and not os.path.exists(p):
                flag("missing-artifact", "medium", f"artifact {p} absent")
                break

    # corrupted metadata: meta exists but lacks required keys
    if meta is not None:
        for k in ("id", "provider", "created_at"):
            if k not in meta:
                flag("corrupted-metadata", "high", f"meta missing '{k}'")
                break

    return {
        "schema": SCHEMA,
        "session_id": sid,
        "checked_at": utcnow(),
        "event_count": len(events),
        "findings": findings,
        "verdict": "ok" if not findings else (
            "integrity-issues" if any(
                f["severity"] == "high" for f in findings) else "warnings"),
        "integrity_id": new_id("int"),
    }
