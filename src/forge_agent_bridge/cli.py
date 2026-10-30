"""forge-bridge CLI (§19.6) — status / doctor / providers / sessions."""

from __future__ import annotations

import json
import sys

import typer

from . import __version__
from .registry import REGISTRY

app = typer.Typer(help="Forge Agent Bridge — universal agent session layer")


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


def main() -> None:
    app()


if __name__ == "__main__":
    sys.exit(main())
