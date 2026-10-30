# Cycle 30.1 — Live Provider Homologation (2026-10-30)

Follow-up to `CYCLE30_1_FINAL_HOMOLOGATION.md`, which classified
**Ready with restrictions** because no provider had been exercised live.
This report records the first real runs. Rule applied throughout:
`unverified` → `verified` only with a captured transcript; nothing fake.

## Results

| Provider | Mechanism | Result | Evidence |
|---|---|---|---|
| Devin CLI 3000.11.234 | `devin acp` JSON-RPC stdio | **homologated** (auth, session, prompt, stream, resume) | `evidence/devin_acp_20261030T093504.jsonl` |
| Copilot CLI 1.0.105 | `copilot -p --output-format json --stream on` | **homologated** (auth, session, prompt, stream, resume) | `evidence/copilot_20261030T093705.jsonl`, `evidence/copilot_session_47153602/` |
| Claude via AWS Bedrock | `bedrock-runtime:Converse` via `product_forge.agents.bedrock_provider` | **blocked — `unavailable:AccessDeniedException`** | `evidence/bedrock_20261030T094324.log` |
| Claude Code 2.1.304 | `claude -p` stream-json | not exercised | — |
| Codex CLI 0.163.0 | `codex exec --json` | not exercised | — |

## Devin — transcript summary

- `initialize` → protocol handshake OK.
- `session/new` → session id `pushy-expert`.
- `session/prompt` with token probe `FORGE-DEVIN-PING-42`:
  - 29 `session/update` notifications; text deltas concatenated to
    exactly `FORGE-DEVIN-PING-42` (`FORGE-DEV` + `IN-PING-` + `42`).
  - Final `stopReason: end_turn`; usage `totalTokens: 136903`
    (`inputTokens: 136846`, `outputTokens: 57`).
- `session/load` → returned session modes/configuration — resume works
  at protocol level.
- Caveat: `AcpAdapter.resume_session()` still raises
  `UnsupportedCapabilityError`; adapter surface does not expose resume
  yet. Streaming through `AcpAdapter.send_prompt()` is synchronous —
  events are drained after `client.prompt()` returns.

## Copilot — mechanism decision + transcript summary

- Mechanism chosen honestly: `gh copilot` is only a passthrough that
  installs the Copilot CLI — it is not the provider API. The real
  mechanism is the installed Copilot CLI 1.0.105 with
  `-p/--prompt --output-format json --stream on` (native JSONL events)
  and `--continue`/`--resume` for session resume.
- Session `47153602-3720-41cc-a9f7-e1f552108593`; server-selected model
  `mai-code-1.1-flash`.
- Token probe `FORGE-COPILOT-PING-7` answered exactly via streamed
  deltas; result event `success`; usage `premiumRequests: 1`.
- `copilot --continue` resumed the session and recalled the token —
  resume verified.
- `copilot sessions list` does not exist in 1.0.105 (`unrecognized
  subcommand 'list'`); session state lives under
  `~/.copilot/session-state/<id>/events.jsonl` — copied to
  `evidence/copilot_session_47153602/`.

## Bedrock — real attempt, honest blocker

Auth path changed from the original plan: the account `702561771161`
(`XedX-Teste`, free tier) is not an IAM Identity Center org account, so
the new `aws login` flow (aws-cli 2.39.2) was used instead of
`aws sso login`. Result: working `default` profile, verified by
`sts:GetCallerIdentity` → `arn:aws:iam::702561771161:root`, region
`sa-east-1`.

The credential chain is proven end-to-end — requests reach
`bedrock-runtime` and AWS answers real service errors:

1. `AccessDeniedException` — *"Your account is currently being verified.
   Verification normally takes less than 2 hours."* (account-level gate
   on model invocation).
2. `ValidationException` — newer Claude IDs (e.g.
   `anthropic.claude-sonnet-4-5-20250929-v1:0`) require an **inference
   profile** in sa-east-1 (e.g. `global.anthropic.claude-sonnet-4-5-*`),
   not on-demand model IDs.
3. `ResourceNotFoundException` — legacy on-demand Anthropic models
   (e.g. `claude-3-haiku`) require the **Anthropic use-case details
   form** submitted once per account.

Status: **`unavailable:AccessDeniedException`** — *not* homologated.
To finish: wait for account verification, submit the Anthropic use-case
form (console → Bedrock → model access), then call
`bedrock_provider` with `PF_BEDROCK_REGION=sa-east-1` and an inference
profile ID. Awaiting retry.

Adapter fix delivered alongside: `MissingDependencyException` (the
`aws login` credential provider requires `botocore[crt]`) previously
escaped as a raw traceback — now maps to `unavailable:dependency`.
`awscrt==0.38.0` installed in the product-forge venv.

## Still unverified (unchanged)

- Claude Code and Codex CLI — installed, never exercised live.
- Tool calls / approvals / denial / cancel on all providers.
- Bridge-level Devin resume and async streaming (adapter gaps above).
