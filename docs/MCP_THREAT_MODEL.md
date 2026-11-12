# MCP Threat Model

Assets: workspace source/config contents, bridge state (sessions,
contexts, pairing files), credentials reachable from the workspace,
gh session, MCP channel integrity, audit trail.

Trust boundaries: (1) MCP client ↔ stdio process, (2) process ↔
filesystem, (3) process ↔ `git`/`gh` subprocesses, (4) host config ↔
server binary.

## Threats → controls → residual

| # | Threat | Control | Residual |
|---|---|---|---|
| T1 | Path traversal (`..`, abs, UNC, device) | `WorkspaceGuard.resolve` — canonicalization, `commonpath`, deny-by-default | Windows check→use race narrowed by re-resolve; cannot fully eliminate on hostile FS |
| T2 | Symlink/junction escape | lstat + reparse screening + inside-root re-check per chain component | Same TOCTOU caveat as T1 |
| T3 | Sensitive-file read (`.env`, keys, tokens) | name + dir denylist applied to direct reads AND tree scans | New secret-file shapes not yet in the denylist → defense-in-depth only |
| T4 | Prompt injection via file/PR content | `untrusted_content` flag + static catalog + policy immutable by content | Model-side resistance is out of server control |
| T5 | Malicious tool args | schema validation (typed, closed props), session-id allowlist regex, repo allowlist + `^[owner]/[repo]$` pattern | New tools must keep the same discipline |
| T6 | Provider spawn / command exec | **no exec tool exists** — catalog is read-only by construction | Any future mutating tool requires explicit policy plumbing |
| T7 | `gh` misuse (other subcommands, token extraction) | fixed argv `pr view --repo --json`, no `gh api`, no shell, allowlisted fields | gh config on the machine could still have other privileges — outside our argv |
| T8 | Oversize/hostile transport | 4 MiB line cap, parse-error recovery, one message per line | A hostile client can still flood slowly — stdio has no rate limiter |
| T9 | Secret leakage via logs/audit/errors | stderr-only logs, minimized audit fields, denylist before reads, typed error envelopes | Audit path itself is on disk — protected 0600, still a file |
| T10 | Client spoofing (trusted-name) | `clientInfo` recorded but never used for authorization | Server cannot verify MCP client identity at all — documented |
| T11 | Config tampering (point to hostile server) | out of scope — host boundary | Mitigation is config file ACL + code review, documented not enforced |
| T12 | Version downgrade to weaker revision | `-32022` for unsupported; legacy versions still enforce the same read-only catalog | A legacy client can't get weaker policy — profiles are transport-independent |
| T13 | Denial of service (slow scan) | depth/file-count/bytes/time caps per tool, 4 MiB message cap | Single-threaded loop — one slow tool blocks the next (documented) |

## Explicit non-goals

- No authentication *from* the MCP client to this server (stdio is a
  local trust boundary — the OS isolates the spawned process).
- No multi-user isolation — one process serves the spawning user.
- No remote transport — stdio only, by design.

## Test coverage

`tests/test_mcp_security.py` maps: T1/T2/T3 (workspace guard), T4/T5
(injection + args), T6 (no-exec), T7 (gh denials), T8/T12 (framing,
versions), T9 (audit minimization). E2E covers channel purity + clean
shutdown (`tests/test_mcp_e2e.py`).
