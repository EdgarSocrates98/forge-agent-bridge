"""forge-bridge CLI (§19.6) — status / doctor / providers / sessions / install."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import typer

from . import __version__
from .registry import REGISTRY

app = typer.Typer(help="Forge Agent Bridge — universal agent session layer")

from ._forge_obsidian.cli import obsidian_app as _obsidian_app

app.add_typer(_obsidian_app("forge-agent-bridge"), name="obsidian")

from .mcp.cli import mcp_app as _mcp_app

app.add_typer(_mcp_app, name="mcp")


def _version_cb(value: bool) -> None:
    if value:
        print(f"forge-bridge {__version__}")
        raise typer.Exit()


@app.callback()
def _main_cb(
    version: bool = typer.Option(
        False, "--version", help="Show version and exit",
        callback=_version_cb, is_eager=True),
) -> None:
    """Forge Agent Bridge — universal agent session layer."""


def _emit(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


@app.command()
def status() -> None:
    """Bridge status + detected provider inventory."""
    det = REGISTRY.detect_all()
    _emit({"version": __version__, "providers_detected": sum(
        1 for d in det if d.executable), "providers": [
            {"id": d.id, "installed": bool(d.executable),
             "auth_state": d.auth_state.value} for d in det]})


@app.command()
def providers() -> None:
    """Full capability matrix per provider."""
    _emit([d.model_dump(mode="json") for d in REGISTRY.detect_all()])


@app.command()
def doctor() -> None:
    """Environment diagnostics — executables, versions, honest auth states."""
    import shutil
    out = []
    for d in REGISTRY.detect_all():
        exe = d.executable
        out.append({"provider": d.id, "executable": exe,
                    "detected": bool(exe) or d.kind == "fake",
                    "path": shutil.which(exe) if exe else None,
                    "auth_state": d.auth_state.value,
                    "note": "auth requires interactive verification" if exe else
                            ("test double" if d.kind == "fake" else "not installed")})
    _emit(out)


@app.command("claude-auth")
def claude_auth(
    mode: str = typer.Option("subscription", help="subscription or bedrock"),
) -> None:
    """Choose Claude authentication on first use; install never prompts."""
    if mode not in {"subscription", "bedrock"}:
        raise typer.BadParameter("choose subscription or bedrock")
    from .local_bridge import state_dir
    path = state_dir() / "provider-config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = {"claude": {"auth_mode": mode}}
    path.write_text(json.dumps(cfg, indent=2) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    if mode == "subscription":
        result = subprocess.run(["claude", "auth", "login"], check=False)
        if result.returncode:
            raise typer.Exit(result.returncode)
        _emit({"provider": "claude-code", "auth_mode": mode, "status": "login_completed"})
        return
    aws = subprocess.run(["aws", "sts", "get-caller-identity", "--output", "json"],
                         check=False, capture_output=True, text=True)
    if aws.returncode:
        _emit({"provider": "claude-code", "auth_mode": mode,
               "status": "aws_credentials_unverified",
               "next_action": "configure AWS credentials with Bedrock access"})
        raise typer.Exit(1)
    _emit({"provider": "claude-code", "auth_mode": mode, "status": "aws_identity_verified"})


@app.command()
def sessions() -> None:
    """List registered adapter sessions (registry-populated only)."""
    _emit({"registered_adapters": [k for k in REGISTRY._adapters] or [],
           "note": "sessions are bridge-process scoped"})


@app.command()
def serve(port: int = typer.Option(8471, min=1, max=65535,
                                   help="Loopback HTTP port."),
          state_dir: str | None = typer.Option(
              None, "--state-dir",
              help="bridge state dir — same as FAB_STATE_DIR "
                   "(default ~/.forge-bridge)")) -> None:
    """Run the local Agent Bridge service on loopback.

    Product Forge uses this command when the user explicitly opens its portal;
    installation itself never starts a provider runtime or asks for credentials.
    """
    if state_dir:
        import os
        os.environ["FAB_STATE_DIR"] = state_dir
    from .local_bridge import serve as serve_bridge

    serve_bridge(port=port)


def _pair_service(base_url: str | None) -> tuple[str, str]:
    """(base_url, master_token) for pairing ops — honest states, never a
    fabricated credential. The master token is read from the resolved
    state dir (FAB_STATE_DIR aware) and used ONLY as the exchange
    credential; it is never printed."""
    import os
    import urllib.parse

    from .local_bridge import resolve_state_dir

    url = (base_url or os.environ.get("FORGE_BRIDGE_URL")
           or "http://127.0.0.1:8471").rstrip("/")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or \
            parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise typer.BadParameter(
            "pairing is loopback-only — non-loopback base URL refused")
    token_file = resolve_state_dir() / "pair.token"
    try:
        token = token_file.read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    return url, token


def _pair_http(url: str, path: str, *, method: str = "GET",
               body: dict | None = None,
               bearer: str = "") -> tuple[int, dict]:
    import http.client
    import urllib.parse

    parts = urllib.parse.urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    conn = http.client.HTTPConnection(parts.hostname, port, timeout=10) \
        if parts.scheme == "http" else \
        http.client.HTTPSConnection(parts.hostname, port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    try:
        conn.request(method, path,
                     body=json.dumps(body) if body is not None else None,
                     headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, json.loads(data or b"{}")
    finally:
        conn.close()


@app.command(name="pair")
def pair_cmd(
    device_name: str = typer.Argument(
        "", help="device name for the minted session token"),
    base_url: str | None = typer.Option(
        None, "--base-url",
        help="bridge URL (env FORGE_BRIDGE_URL; default "
             "http://127.0.0.1:8471)"),
    scopes: str = typer.Option(
        "agent", help="csv of session scopes (clamped to mintable set)"),
    devices: bool = typer.Option(
        False, "--devices", help="list paired devices"),
    revoke: str = typer.Option(
        "", "--revoke", help="revoke a paired device_id"),
) -> None:
    """Pair a device against a running bridge — the real `/pair/*` path.

    Exchanges the master pair.token (read from the state dir) for a
    scoped, expiring session token. Unavailable states are named, never
    faked: no token file → `unavailable:no-pair-token`; service down →
    `unavailable:bridge-not-running`.
    """
    url, master = _pair_service(base_url)
    if not master:
        _emit({"status": "unavailable:no-pair-token",
               "state_dir_checked": True,
               "note": "no pair.token in the state dir — run "
                       "`forge-bridge serve` (or install) once to mint it"})
        raise typer.Exit(1)
    try:
        if devices:
            st, out = _pair_http(url, "/pair/devices", bearer=master)
            _emit({"status": "ok" if st == 200 else f"error:{st}", **out})
            raise typer.Exit(0 if st == 200 else 1)
        if revoke:
            st, out = _pair_http(
                url, f"/pair/devices/{revoke}",
                method="DELETE", bearer=master)
            _emit({"status": "ok" if st == 200 else
                  ("not-found" if st == 404 else f"error:{st}"), **out})
            raise typer.Exit(0 if st == 200 else 1)
        st, out = _pair_http(
            url, "/pair/exchange", method="POST",
            body={"pair_token": master,
                  "device_name": device_name or "cli",
                  "scopes": [s.strip() for s in scopes.split(",")
                             if s.strip()]})
        if st != 201:
            _emit({"status": f"error:{st}", **out})
            raise typer.Exit(1)
        dev = out.get("device") or {}
        _emit({"status": "paired",
               "device_id": dev.get("device_id"),
               "device_name": dev.get("device_name"),
               "scopes": dev.get("scopes"),
               "expires_at": dev.get("expires_at"),
               "session_token": out.get("session_token"),
               "note": "scoped session token (master pair.token is "
                       "never printed)"})
    except OSError:
        _emit({"status": "unavailable:bridge-not-running",
               "base_url": url,
               "note": "start it with `forge-bridge serve` "
                       "(optionally --state-dir/--port)"})
        raise typer.Exit(1)


@app.command()
def install(
    scope: str = typer.Option("user", help="project|workspace|user"),
    profile: str = typer.Option("recommended",
                                help="minimal|recommended|full"),
    components: str | None = typer.Option(
        None, help="csv of service,state,pairing,providers,config"),
    root: str | None = typer.Option(
        None, help="install TARGET root — bridge state lands under "
                   "<root>/.forge-bridge"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes"),
    host: str | None = typer.Option(
        None, help="accepted + ignored — a service forge installs no "
                   "host payloads (delegation contract)"),
    gateway_profile: str | None = typer.Option(
        None, "--gateway-profile",
        help="accepted + ignored — no execution profile "
             "(delegation contract)"),
) -> None:
    """Install the bridge — guided wizard on TTY, JSON receipt with flags.

    Bare `forge-bridge install` on a terminal runs the wizard; any flag
    keeps it non-interactive for CI/scripts.
    """
    from .install import cli as icli
    if guided_requested(scope, profile, components, root, dry_run, yes):
        raise typer.Exit(icli.run_guided_install())
    try:
        _emit(icli.run_flag_install(
            scope=scope, profile=profile, components=components, root=root,
            dry_run=dry_run, yes=yes,
            host=host, gateway_profile=gateway_profile))
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e


def guided_requested(scope, profile, components, root, dry_run, yes) -> bool:
    """Bare command (all defaults, TTY) routes to the wizard."""
    import sys as _s
    defaults = (scope == "user" and profile == "recommended"
                and not components and not root and not dry_run and not yes)
    return defaults and _s.stdin.isatty() and _s.stdout.isatty()


@app.command()
def uninstall(
    scope: str = typer.Option("user", help="project|workspace|user"),
    root: str | None = typer.Option(
        None, help="install TARGET root — state under <root>/.forge-bridge"),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """Remove install-owned files recorded in the ledger —
    preserves pair.token/events/backups/runtime state."""
    from .install import lifecycle
    _emit(lifecycle.uninstall(
        scope=scope,
        root=lifecycle.state_dir_under(Path(root)) if root else None,
        yes=yes))


@app.command(name="install-status")
def install_status(
    scope: str = typer.Option("user", help="project|workspace|user"),
    root: str | None = typer.Option(
        None, help="install TARGET root — state under <root>/.forge-bridge"),
) -> None:
    """Verify install state — honest per-check results."""
    from .install import lifecycle
    _emit(lifecycle.doctor(
        scope=scope,
        root=lifecycle.state_dir_under(Path(root)) if root else None))


def main() -> None:
    if sys.argv[1:] in ([], ["tui"]):
        if sys.stdin.isatty() and sys.stdout.isatty():
            from forge_agent_bridge.ui.home import run_home

            raise SystemExit(run_home())
        if sys.argv[1:] == ["tui"]:
            print("forge-bridge tui requires an interactive TTY", file=sys.stderr)
            raise SystemExit(2)
    app()


if __name__ == "__main__":
    sys.exit(main())
