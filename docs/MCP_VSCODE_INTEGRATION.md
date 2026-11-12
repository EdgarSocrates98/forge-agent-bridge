# VS Code / GitHub Copilot Integration

## What Copilot gets

Once registered, Copilot Chat (agent mode) can call the seven
`forge_*` tools as MCP tools. Copilot owns auth, model, and UX; the
Bridge owns the tool surface. There is no account link and no token
sharing between them.

## Registering

### Managed way (recommended)

```bash
forge-bridge mcp configure --workspace /path/to/workspace
```

writes `.vscode/mcp.json` (workspace) plus the portable files, prints a
receipt per target, and is idempotent. Then in VS Code: **MCP Servers →
the server appears**; or use **Chat → Configure Tools** to enable it.

### Manual `.vscode/mcp.json` (VS Code managed format)

```jsonc
{
  "servers": {
    "forgeAgentBridge": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "forge_agent_bridge.mcp",
               "--profile", "corporate-readonly",
               "--workspace", "${workspaceFolder}"],
      "env": { "PYTHONPATH": "E:\\projetos\\FORJAS\\forge-agent-bridge\\src" }
    }
  }
}
```

- `env.PYTHONPATH` only if the package runs from a source checkout —
  omit it for an installed package.
- `.vscode/mcp.json` uses **`servers`**; the portable format
  (`.mcp.json`, `~/.copilot/mcp-config.json`) uses **`mcpServers`**.
  They are not interchangeable.

### Portable (works across Copilot surfaces)

```jsonc
// .mcp.json or ~/.copilot/mcp-config.json
{ "mcpServers": { "forgeAgentBridge": {
    "type": "stdio", "command": "python",
    "args": ["-m", "forge_agent_bridge.mcp", "--workspace", "."] } } }
```

### VS Code UI

`Ctrl+Shift+P` → `MCP: Add Server…` → **stdio** → enter the command/args
above. The UI writes one of the formats above for you.

## Using it

In Copilot Chat agent mode, tools appear as `forge_*`. Example prompts:

- "run `forge_health` and tell me what's unavailable"
- "use `forge_workspace_summary` then `forge_architecture_review`"
- "`forge_rules_read` on AGENTS.md"  *(returns untrusted-content)*
- "`forge_git_status`" *(honest `unavailable:not-a-git-repository`
  when there's no `.git`)*

`forge_gh_pr_read` needs: `gh` on PATH, `gh auth status` green, the tool
enabled (`local-readonly`/`standard` or `--allow-gh`), and the repo in
`FAB_MCP_GH_REPOS`. All four are checked and reported honestly — it is
*not* a Copilot-prerequisite workaround.

## Verification checklist

1. `forge-bridge mcp doctor --workspace .` → overall `ready` or named
   restrictions.
2. `forge-bridge mcp status` → `forgeAgentBridge` present in targets.
3. In VS Code: the server appears under MCP servers, `tools/list`
   returns 7 tools.
4. `forge_health` reports `profile`, `protocol.negotiated`, and the
   real component states.

## Removal

```bash
forge-bridge mcp configure --workspace . --undo
```

removes **only** the `forgeAgentBridge` entry and preserves everything
else — then delete the workspace/server from VS Code's MCP list.
