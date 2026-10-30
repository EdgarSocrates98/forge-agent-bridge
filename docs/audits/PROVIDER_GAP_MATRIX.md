# Provider Gap Matrix — Cycle 30.2

Honest per-provider capability states. `live` = verified through the
Bridge API against the real provider this cycle; named `unavailable:*`
states are real blockers, not errors to hide.

| Capability | Devin (ACP) | Copilot | Codex | Claude Code | Bedrock |
|---|---|---|---|---|---|
| auth | ✅ live | ✅ live | ✅ live (ChatGPT, isolated CODEX_HOME) | `unavailable:auth` | `unavailable:AccessDeniedException` |
| session create | ✅ live | ✅ live | ✅ live `ses_*` → thread id | — | — |
| real prompt + events | ✅ streamed | ✅ | ✅ `message.completed`, `usage.updated` | — | — |
| usage accounting | ✅ | ✅ | ✅ (67k+ real tokens) | — | — |
| native resume | ✅ `session/load` | ✅ | ✅ `codex exec resume` recalled token | — | — |
| error classification | ✅ | ✅ | ✅ (`runtime.unknown` on codex error items) | — | — |
| approvals | ✅ grant/deny/replay/tamper verified | partial | `unsupported` (sandbox policy; honest raise) | — | — |
| cancel | ✅ | `unverified` | ✅ SIGTERM process-group (unit) | — | — |
| tool calls | ✅ ACP events | `unverified` | `unverified` (read-only sandbox) | — | — |
| subagent events | `unverified` | — | — | — | — |
| attachments | — | — | `unsupported` (honest raise) | — | — |

## Codex homologation detail (this cycle)

- Evidence: `docs/providers/evidence/codex/0.163.0/{turn1,resume}.json`,
  `bridge.log`.
- Isolated `CODEX_HOME` required — live user config loads
  `token-optimizer` plugin whose MCP handshake blocks session init.
- Turns run inside `state_dir/provider-work/codex` (trusted git dir).
- Approvals are intentionally `UnsupportedCapabilityError` — `codex exec`
  is non-interactive; policy is expressed via `--sandbox`, never bypassed.

## Remaining gaps (explicit, not fabricated)

- Claude Code: blocked on user `claude login`.
- Bedrock: blocked on AWS account verification / inference-profile access.
- Copilot + Codex tool-call and cancel: not exercised end-to-end.
- Subagent event surface: not emitted by any homologated provider.
