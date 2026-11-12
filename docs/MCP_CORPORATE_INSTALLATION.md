# Corporate / Restricted-Machine Installation

Scenarios this document covers honestly: no PowerShell, no pip, no
Node/npm/npx/uvx, no Docker, no admin rights, no external network,
manually downloaded repos without `.git`, and — the hardest case — **no
approved Python at all**.

## Prerequisite matrix

| Requirement | Needed for | If absent |
|---|---|---|
| Approved Python ≥ 3.11 on PATH | everything | **blocked: requires-approval** — ask IT; there is no workaround and none is offered |
| `forge_agent_bridge` package importable | server start | set `PYTHONPATH=<repo>/src` or install once where permitted |
| `git` binary | `forge_git_status` | tool reports `unavailable:git-not-on-path` — server still runs |
| `gh` binary + login + repo allowlist | `forge_gh_pr_read` | tool reports `unavailable`/`denied` honestly |
| `.git` directory | git tool | `unavailable:not-a-git-repository` — never `git init` |
| Network | `gh` only | all pure tools still work offline |
| PowerShell | **nothing** | not used anywhere |
| Node/npm/uvx/Docker | **nothing** | not used anywhere |
| Admin rights | **nothing** | everything runs as the user |

## Install paths (pick one)

### A — source checkout (works without pip)

```bash
# repo already on disk (zip download, file share, approved mirror)
cd forge-agent-bridge
python -m forge_agent_bridge.mcp --workspace /path/to/workspace
# or via CLI entry when the venv exists:
PYTHONPATH=src forge-bridge mcp serve --workspace /path/to/workspace
```

`forge-bridge mcp configure` writes the correct `env.PYTHONPATH` into the
MCP config automatically when it detects a `src/` checkout.

### B — installed package (where pip IS approved)

```bash
python -m pip install .
forge-bridge mcp serve --workspace /path/to/workspace
```

### C — wheel on restricted machines

Build once on a permitted machine (`python -m build`), move the `.whl`
through the approved channel, `pip install forge_agent_bridge-*.whl`
or add it to `PYTHONPATH` — the `mcp` package itself is **stdlib-only**
and needs no third-party wheel to serve.

## Configure the host

```bash
forge-bridge mcp configure --workspace /path/to/workspace --dry-run
forge-bridge mcp configure --workspace /path/to/workspace
forge-bridge mcp status     # verify entries
forge-bridge mcp doctor     # honest readiness per check
```

Targets written: `~/.copilot/mcp-config.json` (`mcpServers`),
`<ws>/.mcp.json` (`mcpServers`), `<ws>/.vscode/mcp.json` (`servers` —
the VS Code managed format, NOT interchangeable). Existing servers are
preserved; our entry (`forgeAgentBridge`) is idempotent; `--undo`
removes only ours.

## Verify

```bash
forge-bridge mcp doctor --workspace /path/to/workspace
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"server/discover"}' \
  | python -m forge_agent_bridge.mcp --workspace /path/to/workspace
```

Expected: a single JSON line with `resultType: "complete"` and a
nonzero exit only on misconfiguration.

## Honest blockers

- **No approved Python** → the integration is `requires-approval`.
  There is intentionally no bootstrapper, no embedded interpreter, no
  download — acquiring a runtime is an organizational decision.
- **Read-only home/config dirs** → `mcp configure` reports
  `skipped:file-not-writable` per target instead of forcing.
- **Managed `.vscode/mcp.json`** (org-controlled) → same skip; use the
  portable targets or request the managed entry from IT.
