"""``forge-bridge mcp`` — MCP server lifecycle commands (full runtime).

The ``serve`` verb hands straight to the stdio transport; stdout stays a
clean protocol channel because typer output here only happens BEFORE the
loop starts (and only on usage errors, to stderr via argparse).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

mcp_app = typer.Typer(help="Native MCP stdio server — serve/configure/doctor.")


def _emit(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


@mcp_app.command("serve")
def serve_cmd(
    profile: str = typer.Option(None, help="corporate-readonly|local-readonly|standard"),
    workspace: str = typer.Option(None, help="authorized workspace root"),
    allow_git: bool = typer.Option(None, "--allow-git/--no-git"),
    allow_gh: bool = typer.Option(False, "--allow-gh",
                                  help="enable gh-backed read tools"),
    state_dir: str = typer.Option(None),
) -> None:
    """Run the native MCP stdio server (protocol on stdout only)."""
    from .stdio_server import build_server, serve
    from .workspace import WorkspaceDenied
    try:
        disp = build_server(
            profile, workspace, allow_git=allow_git, allow_gh=allow_gh,
            state_dir=Path(state_dir) if state_dir else None)
    except (WorkspaceDenied, ValueError) as e:
        print(f"mcp error: {e}", file=sys.stderr)
        raise typer.Exit(2)
    raise typer.Exit(serve(disp))


@mcp_app.command("configure")
def configure_cmd(
    workspace: str = typer.Option(None, help="workspace root for .mcp.json/.vscode"),
    profile: str = typer.Option("corporate-readonly"),
    python: str = typer.Option(None, help="approved python executable (default: current)"),
    target: str = typer.Option(None, help="csv subset of targets"),
    tools: str = typer.Option(None, help="csv tool allowlist to publish"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    no_backup: bool = typer.Option(False, "--no-backup"),
    undo: bool = typer.Option(False, "--undo",
                              help="remove only our server entry"),
) -> None:
    """Generate host MCP config (Copilot portable / .mcp.json / .vscode)."""
    import sys as _s

    from . import config as cfg
    ws = Path(workspace).resolve() if workspace else Path.cwd()
    ids = [t.strip() for t in target.split(",")] if target else None
    if undo:
        _emit(cfg.unconfigure(workspace=ws, target_ids=ids, dry_run=dry_run))
        return
    tlist = [t.strip() for t in tools.split(",")] if tools else None
    # PYTHONPATH only when the package runs from a source checkout — an
    # installed package needs no env override.
    pkg_root = Path(__file__).resolve().parents[2]  # .../src
    module_path = str(pkg_root) if not str(pkg_root).startswith(
        str(Path(_s.prefix))) and pkg_root.name == "src" else None
    out = cfg.configure(
        python=python or _s.executable, workspace=ws, profile=profile,
        tools=tlist, target_ids=ids, dry_run=dry_run,
        backup=not no_backup, module_path=module_path)
    _emit(out)


@mcp_app.command("doctor")
def doctor_cmd(
    profile: str = typer.Option(None),
    workspace: str = typer.Option(None),
) -> None:
    """MCP readiness diagnostics — honest per-check states."""
    from .diagnostics import doctor
    _emit(doctor(profile=profile, workspace=workspace))


@mcp_app.command("status")
def status_cmd() -> None:
    """Configured MCP entries across all known target files."""
    import json as _j

    from . import config as cfg
    found = []
    for t in cfg.targets(None) + cfg.targets(Path.cwd()):
        if t.path.is_file():
            try:
                doc = _j.loads(t.path.read_text(encoding="utf-8"))
                srv = (doc.get(t.top_key) or {}).get(cfg.SERVER_NAME)
                found.append({"target": t.id, "path": str(t.path),
                              "configured": srv is not None})
            except (OSError, _j.JSONDecodeError):
                found.append({"target": t.id, "path": str(t.path),
                              "configured": False, "error": "unreadable"})
        else:
            found.append({"target": t.id, "path": str(t.path),
                          "configured": False})
    _emit({"server": cfg.SERVER_NAME, "targets": found})


@mcp_app.command("tools")
def tools_cmd() -> None:
    """List the MCP tool catalog exactly as tools/list serves it."""
    from .tool_registry import list_tools
    _emit({"tools": list_tools()})
