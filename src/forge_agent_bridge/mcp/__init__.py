"""Native MCP stdio server for the Forge Agent Bridge.

Stdlib-only on purpose: this package must run on a bare approved Python
in corporate-restricted environments where pydantic/typer may be absent
("modo mínimo"). Heavier bridge integrations degrade honestly instead of
importing unavailable dependencies.

Protocol coverage (dual-era):
- legacy  (<= 2025-11-25): initialize handshake + notifications/initialized
- modern  (2026-07-28):    stateless, per-request ``_meta`` version metadata
                           + mandatory ``server/discover``
"""

from forge_agent_bridge import __version__ as _bridge_version

MCP_SERVER_NAME = "forge-agent-bridge"
MCP_SERVER_VERSION = _bridge_version

# Ordered newest-first. Legacy family is everything through 2025-11-25;
# modern family starts at 2026-07-28 (handshake removed, see SEP-2575).
SUPPORTED_LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SUPPORTED_MODERN = ("2026-07-28",)
SUPPORTED_VERSIONS = SUPPORTED_MODERN + SUPPORTED_LEGACY

LATEST_LEGACY = SUPPORTED_LEGACY[0]
LATEST_MODERN = SUPPORTED_MODERN[0]

# Meta keys defined by the 2026-07-28 revision.
META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"
