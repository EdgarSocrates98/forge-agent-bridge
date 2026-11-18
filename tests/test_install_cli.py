"""forge-bridge CLI — delegation argv shape + real `pair` path."""
import json

from typer.testing import CliRunner

from forge_agent_bridge.cli import app

runner = CliRunner()


def test_install_delegation_argv(tmp_path):
    """The exact argv the-forge's install auto emits — every declared flag,
    receipt on stdout must be a verifiable forge/InstallReceipt/v1."""
    ws = tmp_path / "ws"
    ws.mkdir()
    res = runner.invoke(app, [
        "install", "--scope", "workspace", "--root", str(ws),
        "--host", "all", "--profile", "recommended",
        "--gateway-profile", "economy", "--yes"])
    assert res.exit_code == 0, res.output
    doc = json.loads(res.output)
    assert doc["schema"] == "forge/InstallReceipt/v1"
    assert doc["forge_id"] == "forge-agent-bridge"
    assert doc["operation"] == "install"
    assert doc["status"] == "completed"
    assert doc["verification"]["status"] in ("PASS", "UNVERIFIED")
    # state under <root>/.forge-bridge — nothing loose at the target root
    assert not (ws / "pair.token").exists()
    assert (ws / ".forge-bridge" / "pair.token").exists()
    # the persisted receipt file is delegation fallback evidence
    assert list((ws / ".forge-bridge" / "receipts").glob("install-*.json"))


def test_install_dry_run_receipt(tmp_path):
    res = runner.invoke(app, [
        "install", "--scope", "workspace", "--root", str(tmp_path),
        "--host", "all", "--dry-run"])
    assert res.exit_code == 0, res.output
    doc = json.loads(res.output)
    assert doc["schema"] == "forge/InstallReceipt/v1"
    assert doc["status"] == "planned"
    assert doc["planned_files"]
    assert not (tmp_path / ".forge-bridge").exists()


def test_install_unknown_component_refused(tmp_path):
    res = runner.invoke(app, [
        "install", "--root", str(tmp_path), "--components", "skills",
        "--yes"])
    assert res.exit_code != 0


def test_pair_no_token(tmp_path, monkeypatch):
    """No pair.token → named unavailable state, never a fake pairing."""
    monkeypatch.setenv("FAB_STATE_DIR", str(tmp_path / "fb"))
    res = runner.invoke(app, ["pair", "dev-1"])
    assert res.exit_code == 1
    doc = json.loads(res.output)
    assert doc["status"] == "unavailable:no-pair-token"


def test_pair_bridge_down(tmp_path, monkeypatch):
    """Token present but no service → honest unavailable, exit 1."""
    sd = tmp_path / "fb"
    sd.mkdir()
    (sd / "pair.token").write_text("tok123")
    monkeypatch.setenv("FAB_STATE_DIR", str(sd))
    res = runner.invoke(app, ["pair", "dev-1", "--base-url",
                              "http://127.0.0.1:1"])
    assert res.exit_code == 1
    doc = json.loads(res.output)
    assert doc["status"] == "unavailable:bridge-not-running"
    assert "tok123" not in res.output  # master token never printed


def test_pair_live_exchange(srv, tmp_path, monkeypatch):
    """End-to-end: exchange mints a scoped session token via /pair/exchange
    against the running bridge (conftest `srv` fixture)."""
    port, tok = srv
    monkeypatch.setenv("FAB_STATE_DIR", str(tmp_path / "fb"))
    res = runner.invoke(app, ["pair", "pytest-dev", "--base-url",
                              f"http://127.0.0.1:{port}"])
    assert res.exit_code == 0, res.output
    doc = json.loads(res.output)
    assert doc["status"] == "paired"
    assert doc["session_token"] and doc["device_id"].startswith("dev_")
    assert doc["scopes"] == ["agent"]
    assert tok not in res.output  # master token never printed
    # the minted session token is real — usable as a bearer credential
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/status",
              headers={"Authorization": f"Bearer {doc['session_token']}"})
    assert c.getresponse().status == 200


def test_pair_devices_and_revoke(srv, tmp_path, monkeypatch):
    port, _tok = srv
    monkeypatch.setenv("FAB_STATE_DIR", str(tmp_path / "fb"))
    base = f"http://127.0.0.1:{port}"
    res = runner.invoke(app, ["pair", "dev-x", "--base-url", base])
    dev = json.loads(res.output)["device_id"]
    res = runner.invoke(app, ["pair", "--devices", "--base-url", base])
    assert res.exit_code == 0
    items = json.loads(res.output)["items"]
    assert any(d["device_id"] == dev for d in items)
    res = runner.invoke(app, ["pair", "--revoke", dev, "--base-url", base])
    assert res.exit_code == 0 and json.loads(res.output)["revoked"] is True


def test_pair_non_loopback_refused(tmp_path, monkeypatch):
    sd = tmp_path / "fb"
    sd.mkdir()
    (sd / "pair.token").write_text("tok123")
    monkeypatch.setenv("FAB_STATE_DIR", str(sd))
    res = runner.invoke(app, ["pair", "dev-1", "--base-url",
                              "http://169.254.1.1:9999"])
    assert res.exit_code != 0
