# Trust Boundary Matrix — Cycle 30.2

Boundaries across the Forge ecosystem. Each row names the enforcement
point and its verification state this cycle.

| Boundary | Enforcement | Verified |
|---|---|---|
| Portal → Bridge | pairing token exchange → session token; `Authorization: Bearer` | ✅ e2e Cycle 30.1 (401/403/201) |
| Portal → Product Forge | PF token; `forge/PortalApi/1` envelopes | ✅ e2e |
| Bridge → provider process | subprocess spawn; `CODEX_HOME`/env isolation; trusted cwd for codex | ✅ codex probe `d42d7ee` |
| Bridge session → principal | `collab.share` binding; resumed sessions bound to resuming principal | ✅ fixed+tested `d42d7ee` |
| Session → product context | `ProductAgentSessionContext` bind at create; `ctxs.assert_allowed` per prompt; revocation blocks further prompts | ✅ e2e + `test_cycle30_1.py` |
| Session → MCP servers | federated registry + context allowlist; denied servers reported `mcp_denied` | ✅ create path; denial honest |
| Approvals | token-bound consume: actor, session, resource, args hashed; replay/tamper/concurrent-use rejected | ✅ e2e + unit tests |
| Bridge → observability | durable `DurableEventStore`, seq continuity, SSE cursor | ✅ e2e SSE + cold replay |
| Provider → filesystem | codex `--sandbox read-only`; workdir-scoped cwd | ✅ spawn config |
| Bridge host | `_ALLOWED_HOSTS` + `FAB_ALLOWED_ORIGINS` origin policy | ✅ `test_origin_policy` |

## Server-side product binding (status)

Session create accepts `product_id`/`workspace_id` and binds a
`ProductAgentSessionContext` server-side; the product→session link is
stored in `meta` + `ctxs`. **Gap carried forward:** binding validates
shape/policy but does not yet re-verify the product exists in Product
Forge at prompt time — documented as open in the final report.

## Negative matrix coverage

Verified (tests/e2e): unauth'd prompt 401, cross-principal prompt 403,
context revoke→403, restricted tool denial, approval forgery/replay/
tamper/concurrent-use, origin policy, CORS. Not yet exercised end-to-end:
SSRF, DNS rebinding, malicious artifact fetch, budget bypass attempt —
each is listed as an open item, not claimed.
