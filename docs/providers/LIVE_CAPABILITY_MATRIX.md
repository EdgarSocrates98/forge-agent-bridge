# Live Provider Capability Matrix — Cycle 30.1

Detected on this host (`uname -s`: Linux). Detection ≠ homologation:
a capability is `verified` only after a live exercised flow with evidence.

| Provider | Binary | Version (recorded) | Authenticated | Session | Streaming | Tool calls | Approvals | Resume | Status |
|---|---|---|---|---|---|---|---|---|---|
| Claude Code | `~/.local/bin/claude` | `2.1.304` | unverified | unverified | unverified | unverified | unverified | unverified | **installed, unverified** |
| Codex CLI | `~/.local/bin/codex` | `codex-cli 0.163.0` | unverified | unverified | unverified | unverified | unverified | unverified | **installed, unverified** |
| Devin CLI | `~/.local/bin/devin` | `3000.11.234 (92c83011d113)` | verified | verified | verified | unverified | unverified | verified¹ | **live-homologated (2026-10-30)** |
| Copilot CLI | `copilot` | `1.0.105` | verified | verified | verified | unverified | unverified | verified | **live-homologated (2026-10-30)** |
| Fake (test) | in-process | n/a | n/a | verified | verified | verified | verified | n/a | **test adapter — not a real provider** |

¹ Resume exercised at raw ACP protocol level (`session/load` returned
modes/configuration) and now implemented in `AcpAdapter.resume_session()`
(2026-10-30); `send_prompt`/`stream_events` stream asynchronously and
emit `turn_complete` with `stopReason` + `usage`.

## Evidence (2026-10-30, real runs)

- **Devin** — `devin acp` JSON-RPC stdio: `initialize` → `session/new`
  (session `pushy-expert`) → `session/prompt` token probe
  `FORGE-DEVIN-PING-42` answered exactly via 29 `session/update`
  notifications (streamed chunks `FORGE-DEV` + `IN-PING-` + `42`),
  `stopReason: end_turn`, real usage `totalTokens: 136903`
  (in 136846 / out 57) → `session/load` resumed the session.
  Transcript: `docs/audits/evidence/devin_acp_20261030T093504.jsonl`
  (51 frames, ~2.2 MB).
- **Copilot** — chosen mechanism: `copilot -p ... --output-format json
  --stream on` (Copilot CLI native JSONL event stream; `gh copilot` is
  only a passthrough installer). Session `47153602-3720-41cc-a9f7-
  e1f552108593`, model `mai-code-1.1-flash`, token probe
  `FORGE-COPILOT-PING-7` answered exactly via streamed deltas, usage
  `premiumRequests: 1`, result `success`. `copilot --continue` resumed
  and recalled the token. Transcript:
  `docs/audits/evidence/copilot_20261030T093705.jsonl` +
  `docs/audits/evidence/copilot_session_47153602/`.
- **Not exercised** (stay `unverified` even for homologated providers):
  tool-call round-trips, permission/approval prompts, denial, cancel.
- Fake-adapter rows are protocol fixtures; they never count as provider
  homologation.

## Known adapter mechanisms (implementation, not homologation)

- `claude`: `claude -p --output-format stream-json --input-format stream-json`
- `codex`: `codex exec --json` + `codex exec resume <thread>`
- `devin`: `devin acp` JSON-RPC stdio
- `copilot`: `copilot -p <prompt> --output-format json --stream on`,
  resume via `copilot --continue` / `--resume <id>`

## To homologate further

For each provider, still to exercise live: tool call → permission
request → approval → denial → cancel. Flip matrix rows only for
exercised capabilities, with transcript evidence. Claude Code and
Codex CLI have no live run yet — every cell stays `unverified`.
