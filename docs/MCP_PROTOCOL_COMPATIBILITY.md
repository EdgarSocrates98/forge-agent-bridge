# MCP Protocol Compatibility

The Bridge implements **two protocol eras**, routed per connection — they
are *not* the same revision and are not treated as such.

| Era | Revision(s) | Session model | Discovery | ping |
|---|---|---|---|---|
| Legacy | `2024-11-05` … `2025-11-25` | `initialize` handshake required | after handshake | supported |
| Modern | `2026-07-28` | stateless — no handshake | `server/discover` mandatory | **removed** |

## Legacy era (≤ 2025-11-25)

Flow: `initialize` → response `{protocolVersion, capabilities,
serverInfo, instructions}` → `notifications/initialized` → requests.

- `protocolVersion` negotiation: the client's proposed version is echoed
  if the server supports it; otherwise the server answers with its
  newest supported legacy version (`2025-11-25`) and the client decides.
- Proposing a *modern*-only version on a legacy handshake →
  `UnsupportedProtocolVersionError` (-32022).
- `ping` → `{}`. `tools/list`, `tools/call` → standard shapes.
- Requests before the handshake → `-32022` (fail closed, not guessed).
- Notifications (no `id`) are never answered. Unknown methods → `-32601`.

## Modern era (2026-07-28)

Handshakes were removed (spec change SEP-2575 and successors):
- `server/discover` → `{resultType: "complete", supportedVersions,
  capabilities, _meta: {"io.modelcontextprotocol/serverInfo": …},
  instructions, ttlMs, cacheScope}`.
- Subsequent requests carry the negotiated version per-request in
  `_meta["io.modelcontextprotocol/protocolVersion"]` — checked against
  `SUPPORTED_MODERN` on every request.
- Version not in the modern family → `UnsupportedProtocolVersionError`
  -32022 with `data: {supported, requested}`.
- `ping` does not exist → `-32601` method not found.
- `tools/list` responses carry server info in `_meta` as the revision
  prescribes.

## Error taxonomy

| Code | Meaning |
|---|---|
| -32700 | parse error (bad JSON/UTF-8, oversize) |
| -32600 | invalid request envelope |
| -32601 | method not found (incl. `ping` on modern) |
| -32602 | invalid params (schema validation) |
| -32603 | internal error (last-resort guard) |
| **-32022** | `UnsupportedProtocolVersionError` `{supported, requested}` |
| -32010 | tool denied by policy `{tool, reason}` |
| -32011 | workspace denied `{tool, reason}` |

## Verified matrix

| Check | Legacy | Modern |
|---|---|---|
| session establishment | `initialize` ✓ tested | `server/discover` ✓ tested |
| tools/list | ✓ | ✓ (with `_meta` server info) |
| tools/call | ✓ | ✓ |
| version refusal | -32022 ✓ | -32022 ✓ |
| ping | `{}` ✓ | -32601 ✓ |
| notification silence | ✓ | ✓ |
| request-id preservation | ✓ (str + int) | ✓ |
| request-before-session | -32022 ✓ | n/a (stateless) |

Tests: `tests/test_mcp_protocol.py`, `tests/test_mcp_e2e.py`.
