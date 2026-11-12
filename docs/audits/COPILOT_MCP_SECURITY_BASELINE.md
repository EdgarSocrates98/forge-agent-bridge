# Copilot MCP — Security Baseline

Companion to `COPILOT_MCP_BASELINE.md` — pre-implementation security
posture of anything a Copilot-facing MCP surface would inherit.

## Trust surface before this work

| Boundary | Then |
|---|---|
| Provider tool auth | `--allow-all-tools` — unrestricted |
| MCP server authorization | post-spawn filtering — **denied servers reachable** |
| HTTP replay | nonce optional everywhere |
| Provider argv env | inherited whole `os.environ` |
| Pairing scopes | self-declared, auto-elevated |
| MCP trust | self-declared at registration |
| Workspace paths | no dedicated guard for an MCP surface |
| Content trust | no untrusted-content marking existed |

## Negative tests that now exist

`tests/test_mcp_security.py` — 20 tests covering traversal, nested `..`,
absolute-outside, NUL, sensitive files (`.env`, `secrets.json`), UNC,
device names, symlink escape (posix), sensitive-dir scan exclusion,
unknown-profile fail-closed, gh/git policy denials, injection-as-data,
rules-read traversal/sensitive, invalid repo, invalid session-id,
denied-call audit trail, audit field minimization.

## Hardening landed (Cycle 0 → MCP surface)

1. Copilot adapter: no `--allow-all-tools`; validated opt-in only.
2. `/agent-sessions`: authorize → filter → spawn ordering, honest
   `denied` ids, orphan-meta cleanup.
3. `FAB_REQUIRE_NONCE` mutating-request enforcement (bootstrap exempt).
4. `cwd` validation before supervisor spawn.
5. Provider session-id consistency (canonical bridge ids).
6. `scrub_env` on provider subprocesses (ACP, Codex).
7. Scope clamp on `/pair/exchange`; trust forced on `POST /mcp`;
   `GET /audit` guarded.
8. `0600` on context writers.
9. Typed HTTP error mapping (`_err_status`) preserving wire contract.
10. MCP surface: `WorkspaceGuard`, denylist, 3 profiles, static
    catalog, `untrusted_content` marking, minimized audit.

## Residual risks (accepted, documented)

- Windows check→use race on workspace reads (no `O_NOFOLLOW`) —
  narrowed by re-resolve; noted in `MCP_THREAT_MODEL.md` T1/T2.
- MCP client identity unverifiable — `clientInfo` is data, never auth.
- Host config tampering — out of server scope; documented.
- New denylist shapes — defense-in-depth, not a guarantee.
- HTTP nonce enforcement remains opt-in (`FAB_REQUIRE_NONCE`) for wire
  compatibility — corporate deployments should set it.
