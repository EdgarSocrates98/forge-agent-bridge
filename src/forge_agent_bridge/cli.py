"""forge-bridge CLI (§19.6) — status / doctor / providers / sessions / install."""

from __future__ import annotations

import json
import sys

import typer

from . import __version__
from .registry import REGISTRY

app = typer.Typer(help="Forge Agent Bridge — universal agent session layer")


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


@app.command()
def sessions() -> None:
    """List registered adapter sessions (registry-populated only)."""
    _emit({"registered_adapters": [k for k in REGISTRY._adapters] or [],
           "note": "sessions are bridge-process scoped"})


@app.command(name="pair")
def pair_cmd(provider: str = "") -> None:
    """Pairing placeholder — local bridge pairing lands with Cycle 19.5."""
    _emit({"status": "unavailable:not-implemented", "provider": provider,
           "note": "pairing is delivered by the local-bridge cycle"})


@app.command()
def install(
    scope: str = typer.Option("user", help="project|workspace|user"),
    profile: str = typer.Option("recommended",
                                help="minimal|recommended|full"),
    components: str | None = typer.Option(
        None, help="csv of service,state,pairing,providers,config"),
    root: str | None = typer.Option(None, help="override state root"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """Install the bridge — guided wizard on TTY, JSON receipt with flags.

    Bare `forge-bridge install` on a terminal runs the wizard; any flag
    keeps it non-interactive for CI/scripts.
    """
    from .install import cli as icli
    if guided_requested(scope, profile, components, root, dry_run, yes):
        raise typer.Exit(icli.run_guided_install())
    _emit(icli.run_flag_install(
        scope=scope, profile=profile, components=components, root=root,
        dry_run=dry_run, yes=yes))


def guided_requested(scope, profile, components, root, dry_run, yes) -> bool:
    """Bare command (all defaults, TTY) routes to the wizard."""
    import sys as _s
    defaults = (scope == "user" and profile == "recommended"
                and not components and not root and not dry_run and not yes)
    return defaults and _s.stdin.isatty() and _s.stdout.isatty()


@app.command()
def uninstall(
    scope: str = typer.Option("user", help="project|workspace|user"),
    root: str | None = typer.Option(None, help="override state root"),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """Remove generated install artifacts — preserves pair.token/events/backups."""
    from pathlib import Path

    from .install import lifecycle
    _emit(lifecycle.uninstall(
        scope=scope, root=Path(root) if root else None, yes=yes))


@app.command(name="install-status")
def install_status(
    scope: str = typer.Option("user", help="project|workspace|user"),
    root: str | None = typer.Option(None, help="override state root"),
) -> None:
    """Verify install state — honest per-check results."""
    from pathlib import Path

    from .install import lifecycle
    _emit(lifecycle.doctor(
        scope=scope, root=Path(root) if root else None))


def main() -> None:
    app()


if __name__ == "__main__":
    sys.exit(main())
