"""forge-bridge install — lifecycle contract (scope/profile/components)."""
import stat

from forge_agent_bridge.install import lifecycle


def test_dry_run_plan_only(tmp_path):
    r = lifecycle.install(scope="user", profile="recommended",
                          root=tmp_path / "fb", dry_run=True)
    assert r["dry_run"] is True and r["applied"] == []
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
    assert r["components"] == ["state"]


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
    assert r["root"].endswith("/.forge-bridge")
