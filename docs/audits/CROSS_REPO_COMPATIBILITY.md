# Cross-Repository Compatibility — Cycle 30.2

| Component | Version | Contract surface | Verified via |
|---|---|---|---|
| forge-agent-bridge | `0.1.0` (`d42d7ee`) | pairing, `/agent-sessions*`, SSE `/stream`, events POST, approvals, context | Cycle 30.1 e2e (40/40) + codex probe |
| product-forge | `0.1.0` (`1fa5f7f`) | `forge/PortalApi/1` envelopes; `/api/v1/products/{pid}/knowledge/query` (`question` field); read-only SQL; dashboard/report/decision/budget/audit | Cycle 30.1 e2e |
| forge-portal | `1.0.0` (`8ed434b`) | Chat Studio `/pf/chat`; localStorage keys `pf.baseUrl`, `pf.token`, `fab.baseUrl`, `fab.sessionToken`, `fab.deviceId` | Chromium e2e screenshot |

## Contract tests present

- `tests/test_cycle30.py` — protocol vocabulary + recovery contracts.
- `tests/test_cycle30_1.py` — approvals atomicity, origin policy,
  context revocation, session integrity endpoint.
- `tests/test_cycle30_2.py` — resume principal-share, codex trusted
  workdir, codex approvals honest-unsupported (new this cycle).
- Product Forge: API envelope + typed `PF-*` errors asserted in its own
  suite (105 tests green).
- Portal: Vitest + Playwright pipeline green on `ubuntu-24.04`.

## Compatibility statements

- Portal ↔ Bridge: pairing + session/event/approval flow — verified.
- Portal ↔ Product Forge: envelope + knowledge citations — verified.
- Bridge ↔ Codex `0.163.0`: session/events/usage/resume — **verified this cycle**.
- Bridge ↔ Devin ACP, Bridge ↔ Copilot: verified Cycle 30.1.
- Bridge ↔ Claude / Bedrock: `unavailable` — see Provider Gap Matrix.
- OS: Linux verified; Windows Job Objects untested (open).

## Known contract pitfalls (documented for consumers)

- `POST /agent-sessions/{sid}/events` — events are **POST**, not GET.
- Prompt body field is `text` (422 `"text required"` otherwise).
- PF knowledge query field is `question`, not `q`.
- Resume route binds the resumed session to the caller's principal.
