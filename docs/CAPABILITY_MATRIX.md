# Forge Agent Bridge — Capability Matrix (Cycle 24)

Honesty contract: a capability is `supported` only when verified against a
real installed provider binary. `unverified` means the mechanism exists but
was not executed end-to-end in this environment. Nothing is simulated.

## Providers

| Provider | Mechanism | Install | Auth | Session create | Stream events | Cancel | Resume | Approvals |
|---|---|---|---|---|---|---|---|---|
| Claude Code | `claude -p --output-format stream-json --input-format stream-json` | supported (PATH) | unverified* | supported | supported (stream-json map) | supported | supported (`--session-id`) | supported (permission events) |
| Codex | `codex exec --json` / `codex resume` | supported (PATH) | unverified* | supported | supported (JSONL map) | supported | supported (`codex resume`) | experimental (exec flags) |
| Devin | `devin acp` (ACP stdio JSON-RPC) | supported (PATH) | unverified* | supported | supported (ACP notifications) | supported (`session/cancel`) | supported (`session/load` if offered) | supported (ACP permission requests) |
| Fake | in-process | supported | n/a | supported | supported | supported | supported | supported |
| Cursor / Aider | — | not registered | — | unsupported | — | — | — | — |

\* Binary presence in `$PATH` is **not** authentication. Auth stays
`unverified` until a real provider call succeeds; the bridge never probes or
stores credentials.

## Bridge surface

| Surface | State | Notes |
|---|---|---|
| Pairing (bearer token, `~/.forge-bridge/pair.token` 0600) | supported | localhost-only bind `127.0.0.1` — hard invariant |
| Session metadata (title/favorite/archive/product/visibility) | supported | JSON store, `0600` |
| Event replay (`after_seq` cursor) | supported | `forge/AgentBridgeEvent/v1` |
| File service (list/read/write/upload/preview/history/restore) | supported | workspace-root scoped, traversal rejected, writes approval-gated |
| Artifacts endpoint | supported | derived from `artifact.created` events |
| Runners (register/health/deregister/place) | partial | **registration + placement gate implemented; remote runner execution is `unverified`** — no real remote worker was homologated; placement to remote is refused until health proves reachability |
| Budgets (scope × window token limits) | supported | real usage from `usage.updated`; 429 on exhaustion |
| Collaboration (share/comment/delegated approval) | supported | roles: owner, delegated approver, observer (read-only) |
| Handoff `remote` | accepted-but-unverified | requires a verified runner; real remote execution not homologated |
| Handoff `provider-resume` | supported | requires real provider session ref; else `FAB-UNSUPPORTED` |
| Handoff `context-rebuild` | supported | `continuity: "reconstructed"` — never claims identical state |
| Audit log | supported | JSONL, append-only |

## Known limits (explicit)

- `X-FAB-Principal` is **self-asserted**: anyone holding the pair token can
  claim any principal. The local trust boundary is the pair token itself;
  multi-user deployments need an authenticated principal source (future work,
  not claimed).
- Remote runner **execution** (process isolation, quotas, network policy on
  a remote host) is not implemented — registration/health/placement is.
- Cross-provider session transfer is never promised; only
  `provider-resume` (same provider) and `context-rebuild` (honest
  reconstruction) exist.
- Event/session durability is JSON-file based; no replay across provider
  restarts beyond provider-native resume.
