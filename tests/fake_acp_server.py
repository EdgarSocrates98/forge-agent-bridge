"""Fake ACP stdio server for adapter tests — speaks JSON-RPC 2.0 with
initialize/session/new/session/load/session/prompt and emits streaming
session/update notifications before each prompt response."""
import json
import sys

LOADED: list[str] = []

for line in sys.stdin:
    req = json.loads(line)
    if "id" not in req:
        continue
    m, rid, params = req["method"], req["id"], req.get("params") or {}
    if m == "initialize":
        out = {"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": 1}}
    elif m == "session/new":
        out = {"jsonrpc": "2.0", "id": rid, "result": {"sessionId": "acp-sess-1"}}
    elif m == "session/load":
        LOADED.append(params.get("sessionId"))
        out = {"jsonrpc": "2.0", "id": rid,
               "result": {"modes": {"availableModes": [{"id": "default"}]}}}
    elif m == "session/prompt":
        for chunk in ("hel", "lo"):
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "method": "session/update",
                "params": {"sessionId": params.get("sessionId"),
                           "update": {"sessionUpdate": "agent_message_chunk",
                                      "content": {"type": "text",
                                                  "text": chunk}}}
            }) + "\n")
        sys.stdout.flush()
        out = {"jsonrpc": "2.0", "id": rid,
               "result": {"stopReason": "end_turn",
                          "usage": {"totalTokens": 12}}}
    else:
        out = {"jsonrpc": "2.0", "id": rid,
               "error": {"code": -32601, "message": f"unknown {m}"}}
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()
