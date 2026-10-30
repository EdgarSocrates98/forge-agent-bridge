"""Forge Agent Bridge — universal agent session layer.

The Bridge owns provider connections, session lifecycle, normalized
events and approval routing. The Portal owns experience; the agent
runtime executes; policies authorize. Public surface only — consumers
(product-forge, forge-portal) import these contracts, never internals.
"""

__version__ = "0.1.0"
EVENT_SCHEMA = "forge/AgentBridgeEvent/v1"
CONTRACT_SCHEMA = "forge/AgentBridgeContract/v1"
