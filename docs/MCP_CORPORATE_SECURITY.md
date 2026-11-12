# Corporate Security Model — MCP Server

## Approval boundary (read this first)

This server **does not bypass corporate controls**. Running it in a
managed environment requires the same organizational approval as any
local executable: the MCP host (VS Code/Copilot) will spawn a Python
process. If your organization does not approve that, do not install —
`mcp doctor` reports `requires-approval` states rather than hiding them.

The server never elevates privileges, never disguises execution, never
extracts internal tokens, and never reaches hosts it was not configured
for.

## Execution profiles

Selected by `--profile` (or `FAB_MCP_PROFILE`), resolved fail-closed —
an unknown profile **refuses to start** (exit 2).

| Profile | Pure tools | git | gh | Depth/files | Intent |
|---|---|---|---|---|---|
| `corporate-readonly` (default) | 5 | ✓ read-only | ✗ | 4 / 600 | Strictest honest posture |
| `local-readonly` | 5 | ✓ | ✓ + allowlist | 6 / 1200 | Personal machines |
| `standard` | 5 | ✓ | ✓ + allowlist | 8 / 2000 | Same read-only surface; mutable tools don't exist yet |

"Read-only" is enforced server-side: the catalog contains **no mutating
tool at all** — there is nothing to escalate to.

## The filesystem trust boundary (`WorkspaceGuard`)

Every path a tool touches resolves through one guard:

- canonicalization + `commonpath` containment (drives, case, normalization)
- `..`, NUL bytes, >512-char paths → denied
- absolute paths outside the root → denied
- UNC paths → denied unless the authorized root itself is UNC
- Windows device names (`con`, `nul`, `com*`…) → denied
- symlinks/junctions/reparse points resolving outside → denied
- sensitive names → denied (`.env*`, `id_rsa*`, `*.pem/key/p12`,
  `credentials*`, `secrets*`, `*.token`, `.netrc`, `.npmrc`,
  gh/azure/kube config dirs, copilot token stores, bridge pairing files)
- bounded reads (`max_file_bytes`), bounded scans (depth + file count),
  deterministic sorted order

Refusals carry only a safe reason code — they never reveal whether the
target exists outside the workspace.

Residual risk, stated honestly: on Windows there is no `O_NOFOLLOW`; the
guard re-resolves immediately before open, which narrows but cannot
fully eliminate a replace-race on a hostile filesystem.

## Subprocess boundary

| Binary | Allowed argv | Constraints |
|---|---|---|
| `git` | `-C <ws> status --porcelain=v2 --branch --no-renames` | fixed, no shell, 10 s timeout, only when `.git` exists |
| `gh` | `pr view <n> --repo <r> --json <fields>` | fixed subcommand, typed int arg, field allowlist, repo allowlist (`FAB_MCP_GH_REPOS`), `gh auth status` verified (30 s cache), 15 s timeout, 64 KiB output cap |

`gh api` and `gh auth token` do not exist as far as this server is
concerned. No mutating verb exists.

## Information hygiene

- Tool results, logs, errors, and audit events carry **no secrets** —
  the workspace denylist removes credential-shaped files before reads.
- Audit records minimized fields only: timestamp, correlation id, event,
  tool, outcome, duration, policy, deny reason. **Never** file contents,
  prompts, or PR bodies.
- Error envelopes are typed (`-32xxx` + reason code); they do not echo
  absolute paths outside the workspace or internal tracebacks to the
  client.
- `forge_health` reports paths the operator already authorized
  (workspace, state dir) — never tokens, never user enumeration.

## Prompt-injection boundary

- `forge_rules_read` and `forge_gh_pr_read` mark outputs
  `untrusted_content: true` with an explicit note: content is data, it
  cannot modify server policy.
- The catalog is static — no document can register tools, change the
  profile, or widen permissions.
- Client name (`clientInfo`) is recorded but **never trusted** as
  corporate identity — it is arbitrary client-declared text.

## What this does NOT protect

- An attacker who already controls the MCP host config can point it at a
  different binary — this server cannot defend the host.
- An approved-but-malicious workspace can contain hostile *content*;
  tools return it marked untrusted, but the *model* must still resist
  injection. The server cannot enforce model behavior.
- `gh` access uses the *user's* existing `gh` login — the server neither
  stores nor refreshes credentials.
