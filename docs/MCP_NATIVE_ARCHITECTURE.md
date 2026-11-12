# MCP Native Architecture — Forge Agent Bridge

Status: **implemented** (v0.2.2+). Verified by `tests/test_mcp_*.py`
(58 tests) and the E2E evidence in `MCP_HOMOLOGATION.md`.

## What this is

The Forge Agent Bridge now exposes a **native MCP server over stdio** —
`forge-bridge mcp serve` or `python -m forge_agent_bridge.mcp`. GitHub
Copilot (VS Code, or any MCP-capable host) can register it as a tool
source and call a fixed catalog of seven **read-only** tools.

```
GitHub Copilot ──stdio/JSON-RPC──► forge-bridge mcp serve
   (auth, model, UX)                    (read-only tool surface)
                                            │
                          ┌─────────────────┼──────────────────┐
                     workspace guard    policy engine      audit sink
                     (path defense)   (profiles: 3)      (mcp.*.jsonl)
```

Copilot remains fully responsible for its own authentication, model
execution, and conversational UX. The Bridge only serves tools; it never
calls a model, never proxies Copilot, and never mutates.

## What it is NOT

- Not a Copilot proxy or token relay.
- Not a replacement for the HTTP bridge (`forge-bridge serve`) — that
  remains the session-management surface, unchanged.
- Not a Permission Broker duplication — tool authorization is a local,
  static, read-only policy, intentionally narrower.
- Not Node.js, not Copilot CLI, not a third-party MCP server.

## Module map (`src/forge_agent_bridge/mcp/`)

| Module | Role |
|---|---|
| `protocol.py` | JSON-RPC 2.0 framing, error codes, version detection |
| `stdio_server.py` | newline-delimited stdin→stdout loop, SIGTERM, EOF |
| `dispatcher.py` | dual-era method routing + tool invocation + caps |
| `tool_registry.py` | static catalog, JSON Schemas, arg validation |
| `security.py` | 3 execution profiles → effective `Policy` |
| `workspace.py` | `WorkspaceGuard` — the filesystem trust boundary |
| `audit.py` | `mcp.*` JSONL event sink (0600, minimized fields) |
| `config.py` | host config writers (Copilot portable/.mcp.json/.vscode) |
| `diagnostics.py` | `mcp doctor` checks |
| `cli.py` | typer sub-app `forge-bridge mcp …` |
| `tools/` | 7 read-only tool implementations |

## Design invariants

1. **Stdlib-only at the MCP boundary.** The entire `mcp/` package imports
   no pydantic/typer — it runs on a bare approved Python in restricted
   environments ("modo mínimo"). The typer CLI is a thin shell.
2. **stdout is a pure protocol channel.** One JSON-RPC message per line,
   UTF-8. Logs, diagnostics, tracebacks → stderr only.
3. **Static catalog.** Tools can never register at runtime; the surface
   is reviewable code.
4. **Policy ≠ annotations.** MCP `readOnlyHint` etc. are hints for the
   client; the server-side `Policy` is the real authorization boundary.
5. **Content is data.** File bodies, PR metadata, and rule docs return
   `untrusted_content: true` — they inform the model but can never
   redefine server policy (prompt-injection boundary).
6. **Fail closed.** Unknown profile → exit 2. Unknown tool → error.
   Denied before schema-validated. Missing workspace → `restricted`.
7. **Honest states.** Every component reports
   `ready|unverified|unavailable:<reason>|restricted|error` — never a
   fabricated healthy picture.

## Transport contract

- Newline-delimited JSON-RPC 2.0 (NOT LSP `Content-Length` framing).
- Notifications are never answered. Stray client responses are ignored.
- Oversize lines (> `policy.max_message_bytes`, default 4 MiB) →
  parse error, connection stays alive.
- Malformed JSON → `-32700`, connection stays alive.
- EOF → clean shutdown (rc 0). SIGTERM → graceful stop + audit.

## Dual-era protocol routing

Era is selected per message (see `MCP_PROTOCOL_COMPATIBILITY.md`):
`initialize` → legacy handshake; `server/discover` or per-request
`_meta` protocol version → modern; anything else before a session →
`UnsupportedProtocolVersionError` (-32022) — fail closed.

## Startup cost

The server imports only stdlib + the `mcp` package: no provider
adapters, no HTTP machinery, no pydantic. Measured cold start and
per-tool timings are recorded in `MCP_HOMOLOGATION.md`.
