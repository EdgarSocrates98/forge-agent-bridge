# Devin CLI/Desktop integration — status

Mechanism (implemented adapter): `devin acp` — ACP server over stdio
(JSON-RPC). Verified CLI facts on this host (`devin acp --help`):
- `devin 3000.11.234 (92c83011d113)`
- `--agent-type`: `summarizer` (no tools, writes
  ~/.local/share/devin/summaries/<session>.md), `review` (read-only +
  shell, diff review), default (omitted → default agent)

Portal path (already wired): Chat Studio → provider `devin` → bridge
spawns `devin acp` child, events stream to UI via SSE. Sessions appear in
Agent Control Center; quality/replay via Forge Lens.

## Homologation state: UNVERIFIED
CLI present + ACP flags confirmed, but no live session was exercised in
this environment (auth/desktop handshake not attempted). To homologate:
`forge-bridge` session create → `provider: devin` → prompt → verify
streamed events + artifacts; record transcript, flip matrix row.
