"""forge-bridge install — lifecycle contract (scope/profile/components)."""
import json
import os
import stat

from forge_agent_bridge.install import lifecycle


def test_dry_run_plan_only(tmp_path):
    r = lifecycle.install(scope="user", profile="recommended",
                          root=tmp_path / "fb", dry_run=True)
    assert r["dry_run"] is True and r["applied"] == []
    assert r["status"] == "planned"
    assert r["operation"] == "install"
    assert not (tmp_path / "fb").exists()
    targets = [s["target"] for s in r["plan"]]
    assert any("pair.token" in t for t in targets)


def test_apply_recommended(tmp_path):
    r = lifecycle.install(scope="user", profile="recommended",
                          root=tmp_path / "fb", yes=True)
    root = tmp_path / "fb"
    assert (root / "events").is_dir() and (root / "backups").is_dir()
    pt = root / "pair.token"
    assert pt.exists()
    # Windows reports inherited NTFS ACLs through st_mode; POSIX mode-bit
    # enforcement is asserted where those bits represent the file policy.
    if os.name != "nt":
        assert stat.S_IMODE(pt.stat().st_mode) == 0o600
    assert (root / "providers.json").exists()
    assert (root / "components.json").exists()
    # honest: CLI-not-on-PATH lands in unverified, never applied
    svc = [s for s in r["unverified"] if s["component"] == "service"]
    assert not svc or "unverified" in svc[0]["result"]


def test_idempotent_second_run_skips(tmp_path):
    lifecycle.install(scope="user", profile="recommended",
                      root=tmp_path / "fb", yes=True)
    tok1 = (tmp_path / "fb" / "pair.token").read_text()
    r = lifecycle.install(scope="user", profile="recommended",
                          root=tmp_path / "fb", yes=True)
    # pair token must not be rotated silently
    assert (tmp_path / "fb" / "pair.token").read_text() == tok1
    assert any(s["action"].startswith("write") and s["result"] == "exists"
               for s in r["skipped"])


def test_minimal_profile_state_only(tmp_path):
    r = lifecycle.install(scope="user", profile="minimal",
                          root=tmp_path / "fb", yes=True)
    assert (tmp_path / "fb").is_dir()
    assert not (tmp_path / "fb" / "pair.token").exists()
    assert not (tmp_path / "fb" / "providers.json").exists()
    assert r["components"]["selected"] == ["state"]


def test_unknown_component_refused(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="unknown components"):
        lifecycle.install(scope="user", components=("skills",),
                          root=tmp_path / "fb")


def test_doctor_honest_states(tmp_path):
    lifecycle.install(scope="user", profile="recommended",
                      root=tmp_path / "fb", yes=True)
    d = lifecycle.doctor(scope="user", root=tmp_path / "fb")
    by = {c["check"]: c["state"] for c in d["checks"]}
    assert by["state-root"] == "ok"
    if os.name == "nt":
        # ``st_mode`` does not expose the effective NTFS ACL.  The doctor
        # must remain honest instead of claiming POSIX 0600 was verified.
        assert by["pair-token-mode"].startswith("warn:")
    else:
        assert by["pair-token-mode"] == "ok"
    assert d["schema"] == "forge/BridgeDoctorReport/v1"


def test_uninstall_preserves_state(tmp_path):
    lifecycle.install(scope="user", profile="full",
                      root=tmp_path / "fb", yes=True)
    r = lifecycle.uninstall(scope="user", root=tmp_path / "fb", yes=True)
    assert (tmp_path / "fb" / "pair.token").exists()   # never removed
    assert not (tmp_path / "fb" / "components.json").exists()
    assert r["kept"]


def test_scope_project_uses_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = lifecycle.install(scope="project", profile="minimal", yes=True)
    # Project roots use the host platform's path separator.
    assert r["state_dir"] == str(tmp_path / ".forge-bridge")


# ---------------------------------------------------------------------
# install-2.1 (cycle-16 wave-07) — forge/InstallReceipt/v1 contract
# ---------------------------------------------------------------------

def test_receipt_v1_envelope(tmp_path):
    """The receipt the-forge's delegation verifier reads."""
    r = lifecycle.install(scope="user", profile="recommended",
                          root=tmp_path / "fb", yes=True)
    assert r["schema"] == "forge/InstallReceipt/v1"
    assert r["forge_id"] == "forge-agent-bridge"
    assert r["operation"] == "install"
    assert r["status"] == "completed"
    assert r["verification"]["status"] in ("PASS", "UNVERIFIED")
    assert isinstance(r["managed_files"], list) and r["managed_files"]
    for f in r["managed_files"]:
        assert {"path", "sha256", "kind", "action"} <= set(f)
        assert f["kind"] in ("config", "state")
    assert isinstance(r["checks"], list) and r["checks"]
    assert r["receipt_id"].startswith("sha256:")
    assert r["target_root"] and r["created_at"]
    # pair TOKEN never reaches the receipt — only its path/hash
    token = (tmp_path / "fb" / "pair.token").read_text().strip()
    assert token not in json.dumps(r)


def test_dry_run_receipt_v1(tmp_path):
    r = lifecycle.install(scope="user", root=tmp_path / "fb", dry_run=True)
    assert r["schema"] == "forge/InstallReceipt/v1"
    assert r["operation"] == "install" and r["status"] == "planned"
    assert r["verification"]["status"] == "UNVERIFIED"
    assert r["planned_files"]
    assert all(f["path"].startswith("fb/") for f in r["planned_files"])


def test_receipt_file_written(tmp_path):
    """Apply persists the receipt under <state>/receipts/ (delegation
    fallback evidence — the `.<state>/receipts` convention)."""
    lifecycle.install(scope="user", profile="recommended",
                      root=tmp_path / "fb", yes=True)
    receipts = list((tmp_path / "fb" / "receipts").glob("install-*.json"))
    assert receipts
    doc = json.loads(receipts[0].read_text())
    assert doc["schema"] == "forge/InstallReceipt/v1"
    assert doc["operation"] == "install" and doc["status"] == "completed"


def test_host_gateway_accepted_ignored(tmp_path):
    r = lifecycle.install(scope="user", root=tmp_path / "fb",
                          dry_run=True, host="all",
                          gateway_profile="economy")
    assert r["host"] is None                      # no host payloads claimed
    assert r["requested_host"] == "all"
    assert r["requested_gateway_profile"] == "economy"
    na = [c for c in r["checks"] if c["status"] == "NOT_APPLICABLE"]
    assert na and "accepted" in na[0]["detail"]


# ---------------------------------------------------------------------
# --root target semantics (install-2.1) — state under <root>/.forge-bridge
# ---------------------------------------------------------------------

def test_state_dir_under(tmp_path):
    assert lifecycle.state_dir_under(tmp_path) == tmp_path / ".forge-bridge"
    # idempotent — an explicit state dir is never nested under itself
    sd = tmp_path / ".forge-bridge"
    assert lifecycle.state_dir_under(sd) == sd


def test_cli_root_is_target_not_state(tmp_path):
    """`forge-bridge install --root <ws>` must never drop pair.token or
    config.json loose at the workspace root (secret-in-repo violation)."""
    from forge_agent_bridge.install import cli as icli
    ws = tmp_path / "ws"
    ws.mkdir()
    r = icli.run_flag_install(scope="workspace", profile="recommended",
                              components=None, root=str(ws),
                              dry_run=False, yes=True)
    assert not (ws / "pair.token").exists()
    assert not (ws / "config.json").exists()
    sd = ws / ".forge-bridge"
    assert (sd / "pair.token").exists()
    assert r["state_dir"] == str(sd) and r["target_root"] == str(ws)
    # a .gitignore guards the state dir from an enclosing VCS
    assert (sd / ".gitignore").read_text().strip() == "*"


def test_scope_workspace_parent(tmp_path, monkeypatch):
    (tmp_path / "sub").mkdir()
    monkeypatch.chdir(tmp_path / "sub")
    r = lifecycle.install(scope="workspace", profile="minimal", yes=True)
    assert r["state_dir"] == str(tmp_path / ".forge-bridge")


# ---------------------------------------------------------------------
# uninstall via ledger — only recorded install-owned files
# ---------------------------------------------------------------------

def test_uninstall_ledger_driven(tmp_path):
    lifecycle.install(scope="user", profile="full",
                      root=tmp_path / "fb", yes=True)
    r = lifecycle.uninstall(scope="user", root=tmp_path / "fb", yes=True)
    assert r["operation"] == "uninstall"
    assert "config.json" in r["removed"] and "providers.json" in r["removed"]
    assert "components.json" in r["removed"]


def test_uninstall_keeps_preserved_config(tmp_path):
    """A config.json that predates the install is user state — write-if-
    absent preserved it, so the ledger never marks it removable."""
    root = tmp_path / "fb"
    root.mkdir(parents=True)
    (root / "config.json").write_text('{"custom": true}')
    lifecycle.install(scope="user", profile="full", root=root, yes=True)
    assert (root / "config.json").read_text() == '{"custom": true}'
    lifecycle.uninstall(scope="user", root=root, yes=True)
    assert (root / "config.json").read_text() == '{"custom": true}'


def test_uninstall_kept_lists_runtime_files(tmp_path):
    root = tmp_path / "fb"
    lifecycle.install(scope="user", profile="recommended",
                      root=root, yes=True)
    # runtime files the service creates at serve-time — never install-owned
    for name in ("pairing.json", "audit.jsonl", "sessions.json",
                 "secrets.json"):
        (root / name).write_text("{}")
    (root / "provider-work").mkdir()
    r = lifecycle.uninstall(scope="user", root=root, yes=True)
    for name in ("pairing.json", "audit.jsonl", "sessions.json",
                 "secrets.json", "provider-work/", "pair.token"):
        assert name in r["kept"], name
        assert (root / name.rstrip("/")).exists()
    assert "events/" in r["kept"] and "backups/" in r["kept"]


def test_uninstall_without_ledger_removes_nothing(tmp_path):
    root = tmp_path / "fb"
    root.mkdir(parents=True)
    (root / "providers.json").write_text("{}")
    r = lifecycle.uninstall(scope="user", root=root, yes=True)
    assert r["removed"] == [] and (root / "providers.json").exists()


# ---------------------------------------------------------------------
# doctor aggregates — honest provider counts
# ---------------------------------------------------------------------

def test_doctor_providers_aggregate_dynamic(tmp_path, monkeypatch):
    lifecycle.install(scope="user", profile="minimal",
                      root=tmp_path / "fb", yes=True)
    d = lifecycle.doctor(scope="user", root=tmp_path / "fb")
    prov = next(c for c in d["checks"] if c["check"] == "providers-detected")
    # the registry catalog has 5 entries — no stale hard-coded denominator
    assert prov["state"].endswith("/5 executables")


# ---------------------------------------------------------------------
# cycle-16.1 wave-08 — forge/InstallLifecycle/v1 + honest FAIL vs
# UNVERIFIED + incremental reinstall (§5.3/§7.4)
# ---------------------------------------------------------------------

def _which_none(_name):
    return None


def _which_bridge(name):
    return "/usr/local/bin/forge-bridge" if name == "forge-bridge" else None


def test_lifecycle_block_schema_and_states(tmp_path):
    """Every receipt carries a derived forge/InstallLifecycle/v1 block in
    the closed vocabulary."""
    r = lifecycle.install(scope="user", profile="recommended",
                          root=tmp_path / "fb", dry_run=True)
    lc = r["lifecycle"]
    assert lc["schema"] == "forge/InstallLifecycle/v1"
    assert lc["state"] in lifecycle.LIFECYCLE_STATES
    assert lc["state"] == "planned"


def test_lifecycle_applied_when_service_unverified(tmp_path, monkeypatch):
    """Shim absent from PATH → verification UNVERIFIED → lifecycle
    `applied` (writes executed, verification pending) — NOT failed."""
    monkeypatch.setattr("shutil.which", _which_none)
    r = lifecycle.install(scope="user", profile="recommended",
                          root=tmp_path / "fb", yes=True)
    assert r["status"] == "completed"
    assert r["verification"]["status"] == "UNVERIFIED"
    assert r["lifecycle"]["state"] == "applied"
    assert not r["failed"]


def test_lifecycle_verified_when_all_pass(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", _which_bridge)
    r = lifecycle.install(scope="user", profile="recommended",
                          root=tmp_path / "fb", yes=True)
    assert r["verification"]["status"] == "PASS"
    assert r["status"] == "completed"
    assert r["lifecycle"]["state"] == "verified"


def test_fail_distinct_from_unverified(tmp_path, monkeypatch):
    """An observed write error is FAIL/failed — evidence of failure —
    never UNVERIFIED (absence of proof). The two states must not blur."""
    monkeypatch.setattr("shutil.which", _which_none)
    # root is a FILE → every mkdir/write under it raises OSError
    blocker = tmp_path / "fb"
    blocker.write_text("not a dir")
    r = lifecycle.install(scope="user", profile="recommended",
                          root=blocker, yes=True)
    assert r["status"] == "failed"
    assert r["verification"]["status"] == "FAIL"
    assert r["lifecycle"]["state"] == "failed"
    assert r["failed"] and all("failed:" in s["result"] for s in r["failed"])
    assert not any(c["status"] == "UNVERIFIED" for c in r["checks"]
                   if c["id"].startswith(("mkdir:", "file:")))
    # …and the honest non-failure case stays UNVERIFIED, not FAIL
    ok = lifecycle.install(scope="user", profile="recommended",
                           root=tmp_path / "ok", yes=True)
    assert ok["verification"]["status"] == "UNVERIFIED"
    assert ok["status"] == "completed"
    assert not ok["failed"]


def test_uninstall_receipt_has_lifecycle(tmp_path):
    lifecycle.install(scope="user", profile="recommended",
                      root=tmp_path / "fb", yes=True)
    r = lifecycle.uninstall(scope="user", root=tmp_path / "fb", yes=True)
    assert r["lifecycle"]["schema"] == "forge/InstallLifecycle/v1"
    assert r["lifecycle"]["state"] == "verified"


def test_doctor_lifecycle_states(tmp_path, monkeypatch):
    # nothing installed → unverified (no installation evidence)
    d = lifecycle.doctor(scope="user", root=tmp_path / "fb")
    assert d["lifecycle"]["state"] == "unverified"
    # installed, CLI shim not on PATH → applied (managed state verified,
    # service probe unproven) — distinct from failed/partially_applied
    monkeypatch.setattr("shutil.which", _which_none)
    lifecycle.install(scope="user", profile="recommended",
                      root=tmp_path / "fb", yes=True)
    d = lifecycle.doctor(scope="user", root=tmp_path / "fb")
    assert d["lifecycle"]["state"] == "applied"
    # managed drift → partially_applied
    import shutil as _sh
    _sh.rmtree(tmp_path / "fb" / "events")
    d = lifecycle.doctor(scope="user", root=tmp_path / "fb")
    assert d["lifecycle"]["state"] == "partially_applied"
    # everything green → ready
    (tmp_path / "fb" / "events").mkdir()
    monkeypatch.setattr("shutil.which", _which_bridge)
    d = lifecycle.doctor(scope="user", root=tmp_path / "fb")
    if d["overall"] == "ok":
        assert d["lifecycle"]["state"] == "ready"
    else:
        # providers-detected=0 is an environment fact, still not failed
        assert d["lifecycle"]["state"] == "applied"


def test_incremental_reinstall_hash_compare(tmp_path, monkeypatch):
    """§7.4: repeated installs never rewrite unchanged assets. Hash-
    compare across two applies: preserved files byte-identical, only the
    ledger + receipts change."""
    import hashlib
    root = tmp_path / "fb"

    def sha(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()

    lifecycle.install(scope="user", profile="full", root=root, yes=True)
    before = {n: sha(root / n) for n in
              ("pair.token", ".gitignore", "config.json", "providers.json")}
    ledger1 = sha(root / "components.json")
    r2 = lifecycle.install(scope="user", profile="full", root=root, yes=True)
    after = {n: sha(root / n) for n in before}
    assert after == before                       # nothing rewritten
    assert sha(root / "components.json") != ledger1  # ledger records the run
    prov = [s for s in r2["skipped"]
            if s["action"] == "write-snapshot"]
    assert prov and prov[0]["result"] == "unchanged"
    assert r2["managed_files"]                   # still fully inventoried
    # each run persists its own receipt — no same-second clobbering
    receipts = sorted((root / "receipts").glob("install-*.json"))
    assert len(receipts) == 2
    assert receipts[0].name != receipts[1].name


def test_incremental_reinstall_updates_changed_detection(tmp_path,
                                                         monkeypatch):
    """A changed provider detection IS rewritten — hash drifts exactly
    when content drifts."""
    import hashlib
    root = tmp_path / "fb"
    lifecycle.install(scope="user", profile="recommended",
                      root=root, yes=True)
    before = hashlib.sha256((root / "providers.json").read_bytes())
    from forge_agent_bridge.registry import REGISTRY

    class _Det:
        def __init__(self, i):
            self._i = i

        def model_dump(self, **_):
            return {"id": f"fake-{self._i}"}

    monkeypatch.setattr(REGISTRY, "detect_all",
                        lambda *a, **k: [_Det(i) for i in range(7)])
    r = lifecycle.install(scope="user", profile="recommended",
                          root=root, yes=True)
    doc = json.loads((root / "providers.json").read_text())
    assert len(doc["providers"]) == 7
    assert hashlib.sha256((root / "providers.json").read_bytes()) != before
    assert any(s["action"] == "write-snapshot" for s in r["applied"])


def test_doctor_zero_executables_not_ok(tmp_path, monkeypatch):
    lifecycle.install(scope="user", profile="minimal",
                      root=tmp_path / "fb", yes=True)
    from forge_agent_bridge.registry import REGISTRY

    class _NoExec:
        executable = ""
        kind = "real"

        def model_dump(self, **_):
            return {}

    monkeypatch.setattr(REGISTRY, "detect_all",
                        lambda *a, **k: [_NoExec()] * 5)
    d = lifecycle.doctor(scope="user", root=tmp_path / "fb")
    prov = next(c for c in d["checks"] if c["check"] == "providers-detected")
    assert prov["state"] == "0/5 executables"
    assert d["overall"] == "incomplete"
