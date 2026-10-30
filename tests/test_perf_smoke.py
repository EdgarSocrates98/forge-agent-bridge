"""Cycle 28.7 — perf smoke (functional-scale, not a load lab).

Measures real elapsed time for session create + prompt + event replay at
1, 5 and 20 concurrent sessions over HTTP, and a 200-event single-session
replay. These are *measurement* tests: they assert generous sanity bounds
(a deadlock/O(n^2) regression blows past them) and record timings — they
are not tuned SLOs.
"""
import http.client
import threading
import time

from conftest import _req

GENUINE_LIMIT_S = 30.0  # far above observed; catches real regressions


def _one_session_lifecycle(port, tok, out, idx):
    """create -> prompt -> events -> delete. Quota refusals (502 FAB-QUOTA)
    are recorded as 'quota' — the runner cap is an honest bound."""
    try:
        st, s = _req(port, tok, "POST", "/agent-sessions",
                     {"provider": "fake", "product_id": f"p-{idx}"})
        sid = s.get("id")
        if not sid:
            code = (s.get("error") or {}).get("code", "")
            out[idx] = "quota" if code == "FAB-QUOTA" else {
                "create_status": st, "create_body": s}
            return
        try:
            _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
                 {"text": f"work {idx}"})
            _, ev = _req(port, tok, "POST",
                         f"/agent-sessions/{sid}/events",
                         {"provider": "fake", "after_seq": 0})
            out[idx] = len(ev["items"])
        finally:
            _req(port, tok, "DELETE", f"/agent-sessions/{sid}")
    except (KeyError, ValueError, OSError, http.client.HTTPException) as e:
        out[idx] = e


def _run_concurrent(port, tok, n):
    out: dict[int, object] = {}
    t0 = time.perf_counter()
    threads = [threading.Thread(target=_one_session_lifecycle,
                                args=(port, tok, out, i))
               for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t0
    return out, elapsed


def test_perf_1_5_20_sessions(srv):
    """1/5/20 concurrent lifecycles. 20 exceeds the runner quota (8) by
    design — FAB-QUOTA is the enforced bound, not a failure."""
    port, tok = srv
    for n in (1, 5, 20):
        out, elapsed = _run_concurrent(port, tok, n)
        errs = {i: v for i, v in out.items()
                if not isinstance(v, int) and v != "quota"}
        assert not errs, f"{n} sessions failures: {errs}"
        ok = sum(1 for v in out.values() if isinstance(v, int))
        quota = sum(1 for v in out.values() if v == "quota")
        assert elapsed < GENUINE_LIMIT_S, \
            f"{n} sessions took {elapsed:.1f}s"
        print(f"\n[perf] {n} concurrent: {elapsed:.2f}s "
              f"(ok={ok}, quota-bound={quota})")


def test_perf_high_volume_replay(srv):
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions", {"provider": "fake"})
    sid = s["id"]
    for i in range(40):  # ~5 events per prompt -> ~200 events
        _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
             {"text": f"turn {i}"})
    t0 = time.perf_counter()
    _, ev = _req(port, tok, "POST", f"/agent-sessions/{sid}/events",
                 {"provider": "fake", "after_seq": 0})
    elapsed = time.perf_counter() - t0
    n = len(ev["items"])
    assert n >= 40
    seqs = [e["seq"] for e in ev["items"]]
    assert seqs == sorted(seqs) and len(set(seqs)) == n  # no loss/dup
    assert elapsed < GENUINE_LIMIT_S
    print(f"\n[perf] replay {n} events: {elapsed:.2f}s")
