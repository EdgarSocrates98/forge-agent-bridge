# Live Provider Capability Matrix — Cycle 30.1

Detected on this host (`uname -s`: Linux). Detection ≠ homologation:
a capability is `verified` only after a live exercised flow with evidence.

| Provider | Binary | Version (recorded) | Authenticated | Session | Streaming | Tool calls | Approvals | Resume | Status |
|---|---|---|---|---|---|---|---|---|---|
| Claude Code | `~/.local/bin/claude` | `2.1.304` | unverified | unverified | unverified | unverified | unverified | unverified | **installed, unverified** |
| Codex CLI | `~/.local/bin/codex` | `codex-cli 0.163.0` | unverified | unverified | unverified | unverified | unverified | unverified | **installed, unverified** |
| Devin CLI | `~/.local/bin/devin` | `3000.11.234 (92c83011d113)` | unverified | unverified | unverified | unverified | unverified | unverified | **installed, unverified** |
| Fake (test) | in-process | n/a | n/a | verified | verified | verified | verified | n/a | **test adapter — not a real provider** |

## Evidence

- Version strings captured 2026-10 via `<cli> --version` on the dev host.
- No live prompt/stream/approval flow was executed against a real provider
  in this cycle — credentials were not confirmed in-scope, and the
  acceptance rule is explicit: *no path reports success without a real
  execution result*. All three CLIs therefore stay `unverified`.
- Fake-adapter rows are protocol fixtures; they never count as provider
  homologation.

## Known adapter mechanisms (implementation, not homologation)

- `claude`: `claude -p --output-format stream-json --input-format stream-json`
- `codex`: `codex exec --json` + `codex exec resume <thread>`
- `devin`: `devin acp` JSON-RPC stdio

## To homologate

Run each provider's flow (auth check → session → prompt → streaming →
tool call → permission request → approval → denial → cancel → resume →
close) in an authorized environment, record the transcript paths, and flip
the matrix rows only for exercised capabilities.
