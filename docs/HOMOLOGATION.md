# Forge Agent Bridge — Homologation Report (Cycle 24)

Suite: `pytest` — **35 tests, all green**; `ruff` clean.
Environment: Linux, Python 3.12, localhost-only bridge.

## E2E matrix

| Scenario | Result | Evidence |
|---|---|---|
| Session create → prompt → stream events → cancel → rename → list | pass | `test_e2e_session_lifecycle` |
| Event replay with `after_seq` cursor | pass | `test_e2e_replay_cursor` |
| Provider registry exposes Claude/Codex/Devin/Fake | pass | `test_neg_unknown_provider` |
| Claude stream-json event mapping | pass | `test_cycle21` (map unit) |
| Codex JSONL event mapping | pass | `test_cycle21` |
| Devin ACP initialize/session/prompt (fake RPC server) | pass | `test_bridge` |

## Negative & security cases

| Case | Expected | Result |
|---|---|---|
| Missing bearer token | 401 | pass |
| Wrong bearer token | 401 | pass |
| Malformed JSON body | 4xx typed error (was 201 — **bug fixed in Cycle 24**) | pass |
| Unknown provider | 4xx | pass |
| Unknown route | 404 | pass |
| Observer prompts | 403 | pass |
| Observer approves | 403 | pass |
| Stranger on private session (hijack) | 403 (**bug fixed in Cycle 24** — private sessions previously allowed any principal) | pass |
| Budget exhausted (limit 0) | 429 | pass |
| Path traversal (`../`, absolute, encoded) | 4xx | pass |
| `provider-resume` without session ref | `FAB-UNSUPPORTED` | pass |
| `context-rebuild` continuity claim | `"reconstructed"` verbatim | pass |
| Deregister protected local runner | 422 | pass |
| Remote placement without verified runner | refused (422/502) | pass |
| File write without approval | `FAB-APPROVAL-REQUIRED` | pass |
| File preview byte cap | enforced | pass |
| Snapshot → restore | content round-trips | pass |

## Bugs found by homologation and fixed

1. **Private-session authz gap**: `assert_can_act` allowed any principal on
   private sessions → now owner-only (`collab.py`).
2. **Malformed JSON created sessions**: body parser swallowed bad JSON →
   now `FAB-VALIDATION` 422; also fixed `BridgeError` import scoping bug it
   exposed.
3. **Version snapshot filename collisions**: timestamp-only names could
   clobber; added monotonic suffix.
4. **Runner deregister crash**: unhandled `FAB-VALIDATION` → now typed 422.

## Release gates

- `pytest -q` — **35/35 green** ✅
- `ruff check src tests` — **clean** ✅
- Localhost-only bind — invariant, asserted by construction (never bound
  to a public interface anywhere in code) ✅
- Pair token 0600 — enforced on write ✅
- No simulated capabilities — provider states honest (`unverified`) ✅

## Not homologated (named, not hidden)

- Real provider end-to-end runs (claude/codex/devin sessions against live
  authenticated CLIs) — binaries present, auth `unverified`; E2E marked as
  mechanism-verified, not live-verified.
- Remote runner execution/isolation — registration + placement gates only.
- Multi-user principal authentication — pair token is the trust boundary.
