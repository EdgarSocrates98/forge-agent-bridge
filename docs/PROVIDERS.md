# Forge Agent Bridge — provider mechanisms

How each adapter talks to its CLI. All adapters implement the
`ProviderAdapter` protocol (`adapter.py`, 14 methods) and normalize output
into `forge/AgentBridgeEvent/v1` envelopes: monotonic `seq`, dedupe,
bounded replay buffer, unknown provider natives preserved verbatim in `raw`.

## Claude Code — `claude`

**Mechanism:** bidirectional stream JSON.

```bash
claude -p --output-format stream-json --input-format stream-json
```

One long-lived child process per session. Prompts and approval responses are
written as JSON lines to stdin; assistant/tool/result/usage events arrive as
JSON lines on stdout and are mapped to `agent.delta`, `tool.call`,
`tool.result`, `turn.completed`, `usage.updated`.

- **Resume:** no native noninteractive resume → **context-rebuild** only
  (never claimed as provider-resume).
- **MCP passthrough:** `mcp_servers` serialized into `--mcp-config` where
  supported.
- **Auth state:** binary on PATH → `ready`-candidate; authenticated run not
  exercised → `unverified` until a real session proves it.

## Codex CLI — `codex`

**Mechanism:** JSONL exec + native resume.

```bash
codex exec --json "<prompt>"          # one-shot JSONL events
codex exec resume <session_id> --json "<prompt>"
```

Each prompt spawns a short-lived process emitting JSONL events (`agent`,
`tool`, `usage`, `result` families), normalized into the shared envelope.

- **Resume:** **provider-resume** — `codex exec resume` re-enters the
  provider's own session; continuity is real, not reconstructed.
- **Approvals:** surfaced as events; sandbox/exec policy passed via exec
  flags on session create.

## Devin — `devin`

**Mechanism:** native ACP (Agent Communication Protocol) over stdio.

```bash
devin acp
```

The bridge's ACP client (`acp.py`) runs JSON-RPC over the child's pipes:
`initialize` → `session/new` → `session/prompt` → `session/cancel` →
`session/close`. Provider notifications arrive as ACP notifications and are
normalized.

- **Resume:** **provider-resume** — `session/new` accepts a prior session
  reference.
- **Approvals:** ACP `session/request_permission` → `approval.requested`;
  bridge approve resolves via the pending request.

## fake — test provider

In-process scripted adapter for tests and offline development: emits a fixed
deterministic event sequence per prompt (delta → usage → turn.completed).
Never advertised as a real capability; `providers` marks it
`kind: "test"`.

## Capability states

| State | Meaning |
|---|---|
| `ready` | binary detected + mechanism confirmed |
| `unverified` | implemented, not yet exercised end-to-end |
| `unavailable:no-binary` | CLI absent from PATH |
| `unavailable:no-auth` | binary present, credentials/sign-in missing |
| `unavailable:transport` | mechanism requires a transport this host lacks |
| `error` | last operation failed (see `last_error`) |

Detection runs in `registry.REGISTRY.detect_all()` — declared catalogs only;
capabilities are never inferred from a name.
