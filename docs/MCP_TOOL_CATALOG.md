# MCP Tool Catalog

Seven tools, all **read-only**, statically registered (no runtime
registration). Annotations are client hints — policy decides. Every tool
returns `structuredContent` plus a `content[0].text` JSON mirror.

| Tool | Needs | Profiles | Risk | What it returns |
|---|---|---|---|---|
| `forge_health` | — | all | low | server version, negotiated revision, profile, workspace auth, components + `unavailable:` reasons, deps |
| `forge_workspace_summary` | workspace | all | low | dir shape, languages, manifests, Forge contracts, `.git` presence, scan limits |
| `forge_architecture_review` | workspace | all | low | deterministic rule checks (tests/CI/lockfile/contracts/rules) + evidence + method limits |
| `forge_context_read` | state dir | all | medium | bound session-context records (expiry/revocation as honest states) |
| `forge_rules_read` | workspace | all | low | catalog of rule docs, or one doc — `untrusted_content: true` |
| `forge_git_status` | workspace + `.git` + git binary + `allow_git` | all\* | low | branch, ahead/behind, dirty count — `unavailable:not-a-git-repository` without `.git` |
| `forge_gh_pr_read` | gh binary + auth + `allow_gh` + repo allowlist | local-readonly, standard | medium | PR fields from allowlist — `untrusted_content: true` |

\* git/gh are additionally gated by `allow_git`/`allow_gh` policy flags.

## Schemas

`tools/list` serves full JSON Schemas (`additionalProperties: false`,
typed params, required fields, min/max). Arg validation is enforced
server-side: unknown keys → `-32602`; wrong types → `-32602`; a
*policy-denied* tool short-circuits to `-32010` **before** schema
validation (fail-closed ordering).

## Annotations (informational)

| Tool | readOnly | destructive | idempotent | openWorld |
|---|---|---|---|---|
| `forge_health` | ✓ | ✗ | ✓ | ✗ |
| `forge_workspace_summary` | ✓ | ✗ | ✓ | ✗ |
| `forge_architecture_review` | ✓ | ✗ | ✓ | ✗ |
| `forge_context_read` | ✓ | ✗ | ✓ | ✗ |
| `forge_rules_read` | ✓ | ✗ | ✓ | ✗ |
| `forge_git_status` | ✓ | ✗ | ✓ | ✗ |
| `forge_gh_pr_read` | ✓ | ✗ | ✓ | ✓ |

## Honest status vocabulary

Tool payloads use named states — `ok`, `unavailable:<reason>`,
`denied:<reason>`, `error:<type>`, `restricted:<reason>` — and never
fabricate success:

- `forge_context_read` → `unavailable:no-context-store` when the bridge
  state dir was never initialized.
- `forge_git_status` → `unavailable:git-not-on-path` /
  `unavailable:not-a-git-repository` / `error:git-timeout`.
- `forge_gh_pr_read` → `unavailable:gh-not-on-path` /
  `unavailable:gh-not-authenticated` / `denied:no-authorized-repos` /
  `denied:repo-not-authorized` / `error:gh-timeout`.

## Equivalence note

Copilot already offers native GitHub tooling in some environments. This
server does **not** duplicate a model capability; `forge_gh_pr_read`
exists for environments where only the Bridge MCP is authorized, and it
is off by default in `corporate-readonly`.
