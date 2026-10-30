# Forge Agent Bridge — security model

## Boundaries

| Boundary | Control |
|---|---|
| Network | binds `127.0.0.1` only — no public interface, ever |
| Authentication | pairing bearer token at `~/.forge-bridge/pair.token` (created `0600` via `forge-bridge pair`); every request checked |
| Identity | `X-FAB-Principal` is self-asserted — it labels ownership/comments/audit, it does not authenticate; the token does |
| Process | raw spawns run in isolated process groups; terminate is SIGTERM → SIGKILL; supervisor cleans all on shutdown |

## File safety

- Root-scoped resolution — `..` escapes and absolute paths outside the
  workspace root are rejected (`FAB-FORBIDDEN`, 403).
- Preview is byte-capped (`truncated: true` when cut).
- `upload` and `restore` are **approval-gated**: without `"approved": true`
  the op returns 403.
- Every mutation snapshots prior bytes to a versioned history (unique
  version ids even inside one timestamp); `restore` reverts by version.

## Authorization (collab)

| Role | May |
|---|---|
| owner | everything: prompt, approve, share, comment, handoff, patch, delete |
| delegated approver | + `approve` (explicitly delegated) |
| observer (workspace visibility) | read/list/comment only — `prompt`, `approve`, `share` → 403 |
| non-owner, private visibility | nothing — 403 |

`assert_can_act` runs before prompt/share; `assert_can_approve` before
approve. Private sessions reject non-owners outright — observers only exist
when visibility is `workspace`.

## Budgets

- Limits by scope `user|workspace|product|provider|session`, window
  `day|month`.
- `budgets.check` runs **before** adapter prompt; exhaustion → 429.
- Usage recorded **after** drain, from real `usage.updated` events;
  sessions without usage events record `estimated: true` — estimates are
  never presented as measured.

## Honesty guarantees

- Remote runners register as `unverified`; placement is refused until a
  health probe returns `ready`.
- The `local` runner cannot be deregistered (422).
- `provider-resume` handoff is refused on providers without native resume;
  `context-rebuild` returns `continuity: "reconstructed"` — never identical.
- Provider auth states are `unverified` until a real authenticated session
  runs; absence is a named `unavailable:*` state, not an error to hide.

## Audit

Append-only trail (`audit.emit`) for: `session.create`, `session.approve`,
`session.share`, `session.handoff`, `runner.register`,
`runner.deregister`, `budget.limit`. Read via `GET /audit` (`X-Tail` cap).

## Secrets

Provider envs receive no credentials from the bridge; persisted documents
are the consumer's responsibility (Product Forge redacts on its side).
Token previews only — the bridge never logs the pair token.
