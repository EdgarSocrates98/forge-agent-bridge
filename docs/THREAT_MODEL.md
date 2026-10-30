# Forge Agent Bridge — Threat Model (Cycle 25)

Scope: the local bridge (`local_bridge.py`, `127.0.0.1` only), its pair token,
session tokens, file service, runners, budgets, and provider process spawns.

## Assets

| Asset | At rest | Exposure if compromised |
|---|---|---|
| Master pair token | `~/.forge/fab/pair.token` (0600) | full local bridge control |
| Device session tokens | `~/.forge/fab/pairing.json` (0600) | scoped bridge ops until expiry/revocation |
| Sessions/events/audit | `~/.forge/fab/*.jsonl` (0600 dirs) | prompt contents, file ops, actor data |
| File service root | user workspace | arbitrary read/write under root |
| Provider credentials | provider env (never injected by bridge) | provider account abuse |

## Trust boundaries

1. **Network → localhost**: bridge binds `127.0.0.1` only; never `0.0.0.0`.
   Foreign `Host` headers rejected (§25.2); CORS allowlist = loopback origins.
2. **Unauthenticated → authenticated**: every route except `/pair/exchange`,
   `/status` requires bearer token (master or valid session token).
3. **Session token → master**: session tokens are scoped (`agent`, `files`,
   `admin`), expire (default 12h), revocable per device, and never carry
   `admin` scope. Master required for `/pair/*` management + `workspace` ops.
4. **HTTP → filesystem**: file ops resolve+validate path under root
   (traversal-safe); writes/restores require a bound one-time approval token.
5. **HTTP → process**: `POST /sessions` spawns only **typed ops**
   (`spawn-provider` + provider id → adapter `SPAWN_ARGV`); arbitrary argv
   is never accepted from the wire.
6. **Local → remote runner**: runner registration validates endpoint URL
   (SSRF — no link-local/metadata/private unless explicitly allowed);
   placement refuses until `health` verified.

## Threat → control

| Threat | Control | Test |
|---|---|---|
| Stolen master token | rotation via `/pair/rotate`; 0600; exchanged once for scoped session token (Portal never persists master) | `test_pairing`, `test_cycle25` |
| Token replay / CSRF | `X-FAB-Nonce` required on mutating ops (Portal sends); approval tokens single-use, bound to op+resource | `test_approval_single_use` |
| Cross-site request to localhost | CORS allowlist; `Host` check; bearer required | `test_foreign_host`, `test_cors` |
| Path traversal | root-scoped resolution rejects `..`/absolute escapes | `test_file_traversal` |
| Oversized body DoS | `MAX_BODY` cap → 413 | `test_body_limit` |
| Arbitrary command exec | typed ops only; `{"cmd": ...}` rejected | `test_typed_spawn` |
| Observer self-escalation | collab roles enforced (observer ≠ prompt/write) | `test_authz_gap` |
| SSRF via runner URL | `ssrf.validate_endpoint` blocks metadata/link-local | `test_runner_ssrf` |
| Secret leakage | `secrets.py` backend; never serialized to logs/env | `test_secrets_backend` |
| Malformed JSON | strict parse → `FAB-BAD-JSON` 400 (was: session created) | `test_bad_json` |

## Known limits (honest)

- `X-FAB-Principal` is self-asserted by the local caller — the **pair token is
  the trust boundary**, not the header. Hardening to signed principals is
  deferred (would need OS-level identity).
- Remote runners remain `unverified` until a real health check passes.
- Provider `auth_state` comes from CLI detection — `unverified` until a live
  authenticated execution succeeds.
- Pair token in localStorage is replaced by a scoped session token; XSS could
  still lift the session token — mitigated by scope, expiry, revocation.
