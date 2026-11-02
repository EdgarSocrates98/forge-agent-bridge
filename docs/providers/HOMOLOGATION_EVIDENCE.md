# Provider homologation evidence

Status: release gate in progress. This document records only locally executed
checks; an installed binary or a detected login is never treated as a pass.

## Matrix — 2026-11-02

| Provider | Auth check | Real prompt | Result | Notes |
|---|---|---|---|---|
| Devin | `devin auth status` | ACP `session/new` + prompt | **passed** | Local credentials file detected; ACP returned session and completion events. |
| GitHub Copilot | CLI present | `copilot -p ... --silent --allow-all-tools` | **passed** | Returned `READY`; adapter emitted content and usage events. |
| Codex | `codex login status` | `codex exec --json --sandbox read-only` | **passed** | Returned `READY`; adapter maps thread/turn/message/usage events. CLI emitted unrelated global-config warnings during shutdown. |
| Claude | `claude auth status --json` | not run | **blocked** | `loggedIn=false`; browser flow requires Claude Max/Ultra/Pro or an API key. AWS session was expired. |

## Evidence rules

- Prompts are synthetic and contain no customer data.
- No token, cookie, credential or provider payload is stored here.
- `passed` means a real provider process returned a response and the Bridge
  observed normalized events; it does not imply every capability is verified.
- Claude remains a release blocker until subscription login or a valid Bedrock
  AWS session is completed and a real prompt is recorded.

## Reproduction

```bash
devin auth status
codex login status
copilot -p 'Reply exactly READY' --silent --allow-all-tools
claude auth status --json
```

## Automated matrix

The redacted harness is now available at `scripts/provider_harness.py` and is
also scheduled nightly in `.github/workflows/provider-homologation.yml`.
It exercises the adapter lifecycle (version/auth/session/prompt/events),
writes only event types and a prompt hash, and exits non-zero when a provider
is blocked or does not produce events:

```bash
uv run python scripts/provider_harness.py --real \
  --output artifacts/provider-matrix.json
```

The local run on 2026-11-02 recorded Devin and Copilot as passed, Claude as
blocked by missing credentials, and Codex as unavailable/timeout under the
current CLI environment. The earlier direct Codex adapter smoke remains the
passing evidence above; the harness intentionally does not convert a timeout
into a pass.

