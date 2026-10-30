"""Cycle 28.6 + Part IX — backups without secrets and /intel/* endpoints."""
from conftest import _req


def _session(port, tok, product="p-1"):
    _, s = _req(port, tok, "POST", "/agent-sessions",
                {"provider": "fake", "product_id": product})
    return s["id"]


def test_intel_route_prefer_fake(srv):
    port, tok = srv
    st, body = _req(port, tok, "POST", "/intel/route",
                    {"task_type": "chat", "required": ["chat"],
                     "prefer": "fake"})
    assert st == 200, body
    assert body["selected"] == "fake"
    assert body["schema"] == "forge/ProviderRouting/v1"


def test_intel_route_unsatisfiable(srv):
    port, tok = srv
    st, body = _req(port, tok, "POST", "/intel/route",
                    {"required": ["teleportation"]})
    assert st == 200, body
    assert body["selected"] is None


def test_intel_quality_and_replay(srv):
    port, tok = srv
    sid = _session(port, tok)
    _req(port, tok, "POST", f"/agent-sessions/{sid}/prompt",
         {"text": "decide: ship it"})
    st, q = _req(port, tok, "GET", f"/intel/{sid}/quality")
    assert st == 200 and q["schema"] == "forge/SessionQuality/v1"
    st, r = _req(port, tok, "GET", f"/intel/{sid}/replay")
    assert st == 200 and r["schema"] == "forge/ReplayDossier/v1"
    assert r["event_count"] > 0 and r["replay_mode"] == "read-only"
    st, d = _req(port, tok, "GET", f"/intel/{sid}/decisions")
    assert st == 200 and "items" in d


def test_intel_context_health(srv):
    port, tok = srv
    sid = _session(port, tok)
    st, body = _req(port, tok, "GET", f"/intel/{sid}/context-health")
    assert st == 200, body
    assert body["schema"] == "forge/ContextHealth/v1"


def test_intel_mode_finops_workspace(srv):
    port, tok = srv
    for path in ("/intel/mode", "/intel/finops", "/intel/workspace"):
        st, body = _req(port, tok, "GET", path)
        assert st == 200, (path, body)
        assert body["schema"].startswith("forge/")


def test_backup_excludes_secrets(srv, tmp_path):
    port, tok = srv
    _session(port, tok)
    st, body = _req(port, tok, "POST", "/backup")
    assert st == 201, body
    assert "pair.token" in str(body["excluded"]) or body["excluded"]
    import tarfile
    with tarfile.open(body["backup"]) as tar:
        names = tar.getnames()
    assert not any(n.endswith("pair.token") for n in names)


def test_backup_restore_requires_approval(srv):
    port, tok = srv
    st, b = _req(port, tok, "POST", "/backup")
    assert st == 201, b
    st, r = _req(port, tok, "POST", "/backup/restore",
                 {"path": b["backup"]})
    assert st == 200 and r["restore"] == "approval-required"
    ap = r["approval_request"]
    st, grant = _req(port, tok, "POST",
                     f"/approvals/{ap['approval_id']}/resolve",
                     {"approved": True})
    assert st == 200 and grant["granted"] is True
    st, r2 = _req(port, tok, "POST", "/backup/restore",
                  {"path": b["backup"],
                   "approval_token": grant["approval_token"]})
    assert st == 200 and "restored" in r2["restore"]
