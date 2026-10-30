"""Cycle 28 — durable event store, redaction, recovery plan (§28)."""

from __future__ import annotations

from conftest import _req


def test_events_persisted_durably(srv, tmp_path) -> None:
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions", {"provider": "fake"})
    sid = s["id"]
    _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
         {"provider": "fake", "text": "hi"})
    from forge_agent_bridge.local_bridge import state_dir
    f = state_dir() / "events" / f"{sid}.jsonl"
    assert f.exists()
    import json
    lines = [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
    assert lines, "no persisted events"
    for e in lines:  # §28.3 fields
        for k in ("seq", "id", "ts", "session_id", "provider", "payload"):
            assert k in e, f"{k} missing"
    assert f.stat().st_mode & 0o777 == 0o600


def test_redaction_before_persist(srv) -> None:
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions", {"provider": "fake"})
    sid = s["id"]
    _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
         {"provider": "fake", "text": "hi"})
    from forge_agent_bridge.events import redact
    out = redact({"api_key": "sk-1", "nested": {"pair_token": "t"},
                  "keep": "ok", "list": [{"secret": "s"}]})
    assert out["api_key"] == "[redacted]"
    assert out["nested"]["pair_token"] == "[redacted]"
    assert out["list"][0]["secret"] == "[redacted]"
    assert out["keep"] == "ok"


def test_durable_replay_cursor(srv) -> None:
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions", {"provider": "fake"})
    sid = s["id"]
    _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
         {"provider": "fake", "text": "one"})
    _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
         {"provider": "fake", "text": "two"})
    _, body = _req(port, tok, "POST", f"/agent-sessions/{sid}/events",
                   {"provider": "fake", "after_seq": 0})
    seqs = [e["seq"] for e in body["items"]]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))
    last = seqs[-1]
    _, body2 = _req(port, tok, "POST", f"/agent-sessions/{sid}/events",
                    {"provider": "fake", "after_seq": last})
    assert body2["items"] == []


def test_retention_marker_not_silent(srv, tmp_path) -> None:
    from forge_agent_bridge.events import DurableEventStore
    st = DurableEventStore(tmp_path / "ev", max_events=3)
    for i in range(6):
        st.append({"schema": "x", "id": f"e{i}", "seq": i + 1,
                   "session_id": "s", "provider": "fake", "payload": {}})
    st.enforce_retention("s")
    evs = st.replay("s")
    assert len(evs) <= 3
    # older events dropped but a marker remains — no silent loss
    all_lines = (tmp_path / "ev" / "s.jsonl").read_text()
    assert "session.retention-trim" in all_lines


def test_recovery_plan_modes(srv) -> None:
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions",
                {"provider": "fake"})
    sid = s["id"]
    st, body = _req(port, tok, "GET",
                    f"/agent-sessions/{sid}/recovery")
    assert st == 200
    r = body["recovery"]
    assert r["schema"] == "forge/SessionRecoveryPlan/v1"
    assert r["mode"] in ("native-resume", "context-rebuild",
                         "read-only-history", "non-resumable")


def test_recovery_readonly_after_close(srv) -> None:
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions",
                {"provider": "fake"})
    sid = s["id"]
    _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
         {"provider": "fake", "text": "work"})
    _req(port, tok, "DELETE", f"/agent-sessions/{sid}")
    st, body = _req(port, tok, "GET",
                    f"/agent-sessions/{sid}/recovery")
    assert st == 200
    # closed session with durable history → reconstructed, not "native"
    assert body["recovery"]["mode"] in ("context-rebuild",
                                        "read-only-history")
    assert body["recovery"]["events_persisted"] > 0


def test_seq_continuity_after_reinit(srv) -> None:
    """seq_floor: after 'restart' the counter never reissues lower seq."""
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions", {"provider": "fake"})
    sid = s["id"]
    _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
         {"provider": "fake", "text": "x"})
    _, body = _req(port, tok, "POST", f"/agent-sessions/{sid}/events",
                   {"provider": "fake", "after_seq": 0})
    top = max(e["seq"] for e in body["items"])
    from forge_agent_bridge.events import envelope, seq_floor
    seq_floor(top)
    e = envelope("message.delta", "fake", sid, {"text": "n"})
    assert e["seq"] > top
