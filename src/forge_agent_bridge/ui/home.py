"""Bare-command home for Forge Agent Bridge."""

from __future__ import annotations

from forge_agent_bridge.ui.kit import NonInteractive, UIContext
from forge_agent_bridge.ui.tui import run_tui


def run_home(*, ctx: UIContext | None = None) -> int:
    if ctx is not None and not ctx.interactive:
        raise NonInteractive("Forge Agent Bridge home requires a TTY")
    return run_tui(ctx=ctx)


__all__ = ["run_home"]
