# Program Status — prompt_evo_pf_continuos.md

| Cycle | Items delivered | Evidence |
|---|---|---|
| 25 — security | typed ops, pair/session tokens, broker authz, approval tokens, SSRF, secrets, threat model, CI+SBOM, risk-tiered PF gates | `5b3e190`, `a20b494`, `a8f092b`, PF `785b717`, Portal `27e57a4` |
| 26 — providers/streaming | versioned capability matrix (`forge/ProviderCapabilityMatrix/1`, 14 caps, honest states); SSE `/agent-sessions/{id}/stream` (cursor/dedup/heartbeat/reconnect); Portal fetch-SSE client (poll=fallback) | `dbeb5fa`, Portal `b3928ee`, `test_cycle26` |
| 27 — context federation | `forge/ProductAgentSessionContext/v1` bind at create, expiry gate, context attach/draft, `forge/MCPServerDescriptor/v1` federation + allowlist (`mcp_denied`), `forge/AgentContextDelta/v1` capture | `2c98fa9`, `test_cycle27` |
| 28 — durability | `DurableEventStore` JSONL (0600) — seq/id/ts/redaction/cursor/retention-marker; restart-safe `seq_floor`; `forge/SessionRecoveryPlan/v1` endpoint | `6755eb0`, `test_cycle28` |

## Honest gaps (not claimed)

- **26.2–26.5**: provider live-homologation pending credentials; Codex App Server / Claude Agent SDK / Devin ACP deep-paths beyond current adapters are `unverified`; browser E2E is contract-simulated only.
- **28.4–28.7**: Windows job-object lifecycle, backups, and 20–100-session perf runs not executed — existing supervisor is POSIX-verified.
- **29**: Chat Studio SSE done; Agent Control Center, Session Compare, Workflow Builder, Artifact Studio, Forge Lens, templates remain unimplemented.
- **30**: no contract-test harness across all three services yet; release gate not run.
- **Part IX**: strategic capabilities (workspace intelligence, marketplace, provider routing, FinOps agent, replay studio, offline mode) not started.
