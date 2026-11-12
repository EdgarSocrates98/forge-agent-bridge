# MCP Troubleshooting

Run `forge-bridge mcp doctor --workspace <ws>` first — it reports each
check as `ready | unverified | unavailable | restricted |
requires-approval | error` with the reason.

## Server won't appear in the host

| Symptom | Likely cause | Fix |
|---|---|---|
| Server absent from MCP list | config written to a different scope than the host reads | `mcp status` shows where entries exist; VS Code workspace needs `.vscode/mcp.json`, portable needs `.mcp.json`/`~/.copilot/mcp-config.json` |
| "command not found" | `python` not on PATH for the host | configure with `--python C:\path\to\approved\python.exe` (absolute path is written verbatim) |
| Server exits immediately | bad profile or workspace | run the `python -m forge_agent_bridge.mcp …` command yourself — errors go to **stderr** |

## Protocol problems

- **"-32022 UnsupportedProtocolVersionError"** → the client proposed a
  revision outside `2024-11-05…2025-11-25` or `2026-07-28`. `data.supported`
  lists what we serve.
- **Tools call works but `initialize` errors** → client is modern-era;
  it should call `server/discover`, not `initialize`.
- **`ping` method-not-found** → the connection negotiated the modern
  revision, where `ping` was removed — this is correct, not a bug.
- **No response to a message** → check it has an `id`; notifications and
  stray responses are never answered, by spec.

## Tool-level honest states

| State | Meaning | Action |
|---|---|---|
| `unavailable:not-a-git-repository` | no `.git` in workspace | expected on zip downloads — not an error |
| `unavailable:git-not-on-path` | git binary absent | install/approve git, or accept limitation |
| `unavailable:gh-not-authenticated` | `gh auth status` failed | `gh auth login` (user action) |
| `denied:no-authorized-repos` | `FAB_MCP_GH_REPOS` empty | set allowlist, or accept the denial |
| `denied:repo-not-authorized` | repo outside allowlist | add to `FAB_MCP_GH_REPOS` |
| `unavailable:no-context-store` | bridge state dir absent | run `forge-bridge serve` once, or accept |
| `-32010` | policy denial | tool is disabled by the active profile |
| `-32011` | workspace denial | path failed the guard — reason code tells why |

## Config writers

- `skipped:file-not-writable` → the target is managed/read-only; the
  server refuses to force it (by design). Use a writable target or ask
  IT to manage the entry.
- Config exists but our entry vanished → something rewrote the file;
  re-run `mcp configure` (idempotent).
- `--undo` removed too much → it only removes `forgeAgentBridge`;
  if more is missing, another tool edited the file.

## Audit forensics

`$FAB_STATE_DIR/mcp_audit.jsonl` (default `~/.forge-bridge/`): one JSON
per line — `event`, `tool`, `outcome`, `deny_reason`, `duration_ms`,
`policy`. Look for `mcp.tool.denied` to explain surprising denials.

## Still stuck

Collect: `mcp doctor` output, the exact `python -m forge_agent_bridge.mcp`
stderr text (stdout stays clean), and the audit tail. Secrets are not in
any of these by design — if you find one, that is a bug: report it.
