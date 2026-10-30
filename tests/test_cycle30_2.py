"""Cycle 30.2 — regressions found during live provider homologation.

- Resumed sessions must be shared with the requesting principal (found
  via real Codex probe: prompt on resumed session → FAB-FORBIDDEN).
- Codex adapter must run turns inside a trusted (git) workdir.
"""
from __future__ import annotations

import pytest

from conftest import _req
from forge_agent_bridge.adapter import BridgeError
from forge_agent_bridge.providers.codex import CodexAdapter


def test_resumed_session_shared_with_principal(srv):
    """POST /agent-sessions/{sid}/resume binds the new session to the
    caller — without the collab share its own creator cannot prompt."""
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions",
                {"provider": "fake"}, principal="alice")
    st, r = _req(port, tok, "POST", f"/agent-sessions/{s['id']}/resume",
                 {"provider": "fake", "session_ref": s["id"]},
                 principal="alice")
    assert st == 201, r
    sid2 = r["id"]
    st, b = _req(port, tok, "POST", f"/agent-sessions/{sid2}/prompt",
                 {"text": "hello"}, principal="alice")
    assert st == 200, b
    assert b["accepted"] is True


def test_provider_resume_handoff_shared(srv):
    """The handoff provider-resume path shares the session as well."""
    port, tok = srv
    _, s = _req(port, tok, "POST", "/agent-sessions",
                {"provider": "fake"}, principal="alice")
    st, b = _req(port, tok, "POST",
                 f"/agent-sessions/{s['id']}/handoff",
                 {"mode": "provider-resume"}, principal="alice")
    # fake has no provider_session_ref → honest FAB-UNSUPPORTED, or a
    # shared session — either way it must not produce an orphaned one.
    if st == 201:
        sid2 = b["session"]["id"]
        st2, p = _req(port, tok, "POST",
                      f"/agent-sessions/{sid2}/prompt", {"text": "hi"},
                      principal="alice")
        assert st2 == 200, p
    else:
        assert b["error"]["code"] == "FAB-UNSUPPORTED"


def test_codex_workdir_is_trusted(tmp_path, monkeypatch):
    """Turns spawn inside a git-initialized dir — codex refuses to run
    outside a trusted directory (found: prompts drained 0 events when
    the bridge cwd was ~)."""
    monkeypatch.setenv("FAB_PROVIDER_WORKDIR", str(tmp_path / "pw"))
    a = CodexAdapter()
    cwd = a._cwd()
    import os
    assert cwd is not None and os.path.isdir(os.path.join(cwd, ".git"))
    assert a._cwd() == cwd  # idempotent


def test_codex_workdir_absent_returns_none(monkeypatch):
    monkeypatch.delenv("FAB_PROVIDER_WORKDIR", raising=False)
    a = CodexAdapter(workdir=None)
    assert a._cwd() is None


def test_codex_approvals_honestly_unsupported():
    a = CodexAdapter()
    with pytest.raises(BridgeError):
        a.respond_to_approval("ap_x", True)
