# Forge Agent Bridge — HTTP API reference

Base URL: `http://127.0.0.1:<port>` (localhost only — the service refuses
external binding).

## Authentication

Every request requires the pairing token:

```
Authorization: Bearer $(cat ~/.forge-bridge/pair.token)
```

Optional principal header (default `local`):

```
X-FAB-Principal: edgar
```

Self-asserted — the pair token is the trust boundary; the principal labels
ownership, comments and audit entries.

## Responses

Success bodies are plain JSON. Errors are typed envelopes:

```json
{"error": {"code": "FAB-VALIDATION", "message": "text required"}}
```

| Condition | HTTP | Code family |
|---|---|---|
| malformed JSON body | 422 | `FAB-VALIDATION` |
| missing/invalid field | 422 | `FAB-VALIDATION` |
| non-object JSON body | 422 | `FAB-VALIDATION` |
| auth missing/wrong token | 401 | `FAB-AUTH` |
| forbidden action (observer, non-owner) | 403 | `FAB-FORBIDDEN` |
| unknown route/entity | 404 | `FAB-404` / `FAB-NOT-FOUND` |
| budget exhausted | 429 | `FAB-BUDGET-*` |
| adapter/provider failure | 502 | `FAB-ERROR`, adapter codes |

## Health & catalog

### `GET /status`
→ `{"ok": true, "workspace_root": "...", "running": 2}`

### `GET /providers`
→ `{"items": [ProviderDescriptor...]}` — id, display name, binary path or
`null`, auth state (`ready`/`unverified`/`unavailable:*`), supported
mechanisms.

### `GET /audit`
→ `{"items": [AuditEvent...]}` — newest last; `X-Tail: N` header caps count
(default 50).

## Process sessions (raw supervisor)

### `POST /sessions`
Body: `{"cmd": ["sleep","30"], "cwd": "."}` → 201 `{"session_id": "ses_…"}`.
`cmd` must be a string list. Spawns in its own process group.

### `DELETE /sessions/{id}`
→ `{"terminated": true}` (404 if already gone). SIGTERM → SIGKILL escalation.

## Agent sessions

### `POST /agent-sessions`
Body:

```json
{
  "provider": "claude",                // claude | codex | devin | fake
  "product_id": "payments",
  "workspace_id": "ws_1",
  "title": "retry analysis",
  "visibility": "private",             // private | workspace
  "runner": "local",                   // placement refused if runner not ready
  "mcp_servers": {"pf": {"command": "productforge", "args": ["mcp","serve"]}}
}
```

→ 201 — session object (`forge/AgentBridgeEvent` schema fields) plus `meta`
block. Side effects: runner placement check, collab owner record, audit
`session.create`.

### `GET /agent-sessions`
→ `{"items": [...]}` — live sessions from orchestrators **plus** closed
sessions persisted in the metadata store (`state: "closed"`).

### `PATCH /agent-sessions/{sid}`
Body keys allowed: `title`, `product_id`, `workspace_id`, `favorite`,
`archived`, `visibility`, `notes`. → `{"meta": {...}}`

### `DELETE /agent-sessions/{sid}`
→ `{"closed": bool, "archived": true}` — closes via provider adapter if
reachable; metadata always archived.

### `POST /agent-sessions/{sid}/prompt`
Body: `{"text": "...", "attachments": [{"path": "...", "mime": "..."}]}`

Gates, in order: session exists → `collab.assert_can_act` (owner; observers
forbidden) → `budgets.check` (429 on exhaustion) → adapter prompt → drain →
usage recorded from `usage.updated` events (`estimated: true` when absent).

→ `{"accepted": true, "events_drained": N}`

### `POST /agent-sessions/{sid}/events`
Body: `{"after_seq": 0}` → `{"items": [Event...]}` — replay cursor; only
events with `seq > after_seq`.

### `POST /agent-sessions/{sid}/cancel`
→ `{"cancelled": true}`

### `POST /agent-sessions/{sid}/resume`
Body: `{"session_ref": "<provider session id>"}` → 201 session object.
Provider-resume supported on Codex + Devin; Claude uses context-rebuild via
`/handoff` instead.

### `POST /agent-sessions/{sid}/approve`
Body: `{"approval_id": "...", "approved": true}` — caller must be owner or
`delegated_to` principal. → `{"resolved": true}`; audit `session.approve`.

### `POST /agent-sessions/{sid}/share`
Body: `{"visibility": "workspace", "observers": ["ana"], "delegated_to": "ana"}`
— owner only. → `{"collab": {...}}`; audit `session.share`.

### `POST /agent-sessions/{sid}/comment`
Body: `{"text": "..."}` → `{"comments": [...]}`.

### `POST /agent-sessions/{sid}/handoff`
Body:

```json
{
  "mode": "provider-resume",   // remote | provider-resume | context-rebuild
  "target_runner": "runner-b", // remote mode
  "session_ref": "...",        // provider-resume mode
  "context": "..."             // context-rebuild mode
}
```

Modes:
- `remote` — place session on another ready runner (refused if unverified).
- `provider-resume` — native provider resume; honest refusal when the
  provider can't resume.
- `context-rebuild` — new session seeded with reconstructed context; returns
  `continuity: "reconstructed"` — never "identical".

→ handoff record; audit `session.handoff`.

### `POST /agent-sessions/{sid}/artifacts`
→ `{"items": [ArtifactRef...]}` — adapter-provided artifact references.

## Files

All under `POST /files/{op}` with `path` relative to the workspace root.
Traversal (`..`, absolute outside root) → 403 `FAB-FORBIDDEN`.

| op | body | returns |
|---|---|---|
| `list` | `{"path": "dir"}` | `{"items": [{name, kind, size}...], "root": "..."}` |
| `preview` | `{"path": "f.md"}` | `{path, content, truncated, size}` — capped bytes |
| `download` | `{"path": "f.md"}` | `{path, content_b64}` |
| `upload` | `{"path": "f.md", "content_b64": "...", "approved": true}` | snapshot record + write result — `approved` required |
| `history` | `{"path": "f.md"}` | `{"items": [{version, ts, snapshot}...]}` |
| `restore` | `{"path": "f.md", "version": "v…", "approved": true}` | restored snapshot — `approved` required |

Every mutation snapshots the prior bytes first; snapshots are uniquely
versioned even within one timestamp.

## Runners

| Method | Path | Purpose |
|---|---|---|
| GET | `/runners` | list runners with states |
| POST | `/runners` | register remote `{id, kind:"remote", endpoint, labels, quota_sessions}` → starts `unverified` |
| POST | `/runners/{id}/health` | probe → `ready`/`error` |
| POST | `/runners/{id}/deregister` | drain + remove — the `local` runner returns 422 |

Placement (`agent-sessions` create) is refused for `unverified`/`error`
remote runners.

## Budgets

| Method | Path | Purpose |
|---|---|---|
| GET | `/budget` | usage summary per scope |
| POST | `/budget/limits` | `{scope, key, window, tokens}` → 201 limit record |

Scopes: `user`, `workspace`, `product`, `provider`, `session`.
Windows: `day`, `month`. Checked before every prompt; exhaustion → 429.

## Errors

| Code | Meaning |
|---|---|
| `FAB-VALIDATION` | malformed/invalid request |
| `FAB-AUTH` | missing or wrong bearer token |
| `FAB-FORBIDDEN` | authz denied (observer acting, traversal, unapproved write) |
| `FAB-NOT-FOUND` / `FAB-404` | unknown session/route |
| `FAB-BUDGET-*` | budget exhausted |
| `FAB-ERROR` | adapter/provider/transport failure |

## Cycle 26–28 additions

### Streaming (§26.6)
| Method | Path | Notes |
|---|---|---|
| GET | `/agent-sessions/{id}/stream?after_seq=N` | SSE; `id: <seq>` cursor, `Last-Event-ID` honored, `: hb` heartbeats, ~55s bounded → reconnect with cursor |

### Context (§27)
| Method | Path | Body → Result |
|---|---|---|
| GET | `/agent-sessions/{id}/context` | → bound `forge/ProductAgentSessionContext/v1` |
| POST | `/context/draft` | context fields → draft context (identity bound to actor) |
| POST | `/context/attach` | `{session_id, context}` → rebind + audit |
| POST | `/context/delta` | `forge/AgentContextDelta/v1` → `{recorded, review}` |
| GET | `/context/deltas?product_id=&review=` | → `{items}` |

### MCP federation (§27.5)
| Method | Path | Notes |
|---|---|---|
| GET | `/mcp` | list `forge/MCPServerDescriptor/v1` entries |
| POST | `/mcp` | register `{server_id, name, capabilities, ...}` |
| POST | `/mcp/{id}/health` | `{health}` → verified/unverified/error |

Session create accepts `context` (bound at birth, `mcp_registry` allowlist)
and `mcp_servers` (filtered through federation trust → `mcp_denied`).

### Recovery (§28.2)
| Method | Path | Notes |
|---|---|---|
| GET | `/agent-sessions/{id}/recovery` | `forge/SessionRecoveryPlan/v1` — mode: native-resume / context-rebuild / read-only-history / non-resumable |

### Durable events (§28.3)
Events persist to `~/.forge-bridge/events/{sid}.jsonl` (0600): seq, id, ts,
session/turn/provider, redacted payload. Replay without duplication;
retention writes a `session.retention-trim` marker — never silent loss.
