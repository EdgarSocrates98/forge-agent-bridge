"""JSON-RPC 2.0 + MCP message framing for the stdio transport.

Pure stdlib. One JSON object per line (the stdio transport framing —
NOT LSP Content-Length framing, which this protocol does not use).
"""

from __future__ import annotations

import json
from typing import Any

from . import (
    META_PROTOCOL_VERSION,
    SUPPORTED_VERSIONS,
)

# -- JSON-RPC error codes ----------------------------------------------------
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
# server-defined (JSON-RPC reserves -32099..-32000 for implementation use)
UNSUPPORTED_VERSION = -32022          # spec-mandated UnsupportedProtocolVersionError
TOOL_DENIED = -32010                  # forge: policy denied the tool call
WORKSPACE_DENIED = -32011             # forge: workspace/root rejected


def make_result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def make_error(msg_id: Any, code: int, message: str,
               data: Any | None = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": err}


def unsupported_version(msg_id: Any, requested: Any) -> dict[str, Any]:
    """UnsupportedProtocolVersionError — shape mandated by the spec."""
    return make_error(
        msg_id, UNSUPPORTED_VERSION, "Unsupported protocol version",
        {"supported": list(SUPPORTED_VERSIONS), "requested": requested})


def is_request(msg: Any) -> bool:
    """A JSON-RPC request carries a method and an id (response expected)."""
    return (isinstance(msg, dict) and "method" in msg
            and "id" in msg and msg.get("id") is not None)


def is_notification(msg: Any) -> bool:
    """A JSON-RPC notification carries a method but no id — never answered."""
    return (isinstance(msg, dict) and "method" in msg
            and ("id" not in msg or msg.get("id") is None))


def validate_envelope(msg: Any) -> str | None:
    """Structural check → error string or None."""
    if not isinstance(msg, dict):
        return "message is not a JSON object"
    if msg.get("jsonrpc") != "2.0":
        return "jsonrpc must be '2.0'"
    if "method" in msg and not isinstance(msg["method"], str):
        return "method must be a string"
    if "method" not in msg and "result" not in msg and "error" not in msg:
        return "neither request, notification nor response"
    if "id" in msg and not isinstance(msg["id"], (str, int, float, bool, type(None))):
        return "id must be string|number|null"
    return None


def parse_line(raw: bytes, *, max_bytes: int) -> tuple[dict[str, Any] | None,
                                                     dict[str, Any] | None]:
    """Decode one transport line → (message, parse_error_response).

    ``parse_error_response`` is a ready-to-send error object (id null) when
    decoding failed; the caller sends it and keeps reading.
    """
    if len(raw) > max_bytes:
        return None, make_error(None, PARSE_ERROR,
                                f"message exceeds {max_bytes} bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, make_error(None, PARSE_ERROR, "invalid UTF-8")
    try:
        msg = json.loads(text)
    except json.JSONDecodeError as e:
        return None, make_error(None, PARSE_ERROR, f"invalid JSON: {e.msg}")
    err = validate_envelope(msg)
    if err:
        return None, make_error(msg.get("id") if isinstance(msg, dict) else None,
                                INVALID_REQUEST, err)
    return msg, None


def requested_version(msg: dict[str, Any]) -> Any:
    """Modern-era declared protocol version — ``params._meta`` first,
    top-level ``_meta`` as fallback (both are spec-legal placements)."""
    params = msg.get("params")
    if isinstance(params, dict):
        meta = params.get("_meta")
        if isinstance(meta, dict) and META_PROTOCOL_VERSION in meta:
            return meta[META_PROTOCOL_VERSION]
    meta = msg.get("_meta")
    if isinstance(meta, dict):
        return meta.get(META_PROTOCOL_VERSION)
    return None


def version_supported(v: Any, family: tuple[str, ...]) -> bool:
    return isinstance(v, str) and v in family
