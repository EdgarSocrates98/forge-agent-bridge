"""ACP client (§19.2) — JSON-RPC over stdio: handshake, version
negotiation, session lifecycle, prompt, streaming, cancel.

Transport: newline-delimited JSON-RPC 2.0 on the agent's stdin/stdout.
No SDK is vendored; the wire contract is documented ACP semantics.
"""

from __future__ import annotations

import itertools
import json
import subprocess
import threading
from collections.abc import Iterator
from typing import Any

from .adapter import BridgeError, ProviderUnavailableError

_ids = itertools.count(1)
PROTOCOL_VERSION = 1


class AcpClient:
    """Minimal ACP stdio client. One client per spawned agent process."""

    def __init__(self, cmd: list[str], timeout_s: float = 30.0):
        self.cmd, self.timeout_s = cmd, timeout_s
        self.proc: subprocess.Popen[bytes] | None = None
        self._pending: dict[int, dict[str, Any]] = {}
        self._notifications: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self.protocol_version: int | None = None

    # -- transport ---------------------------------------------------------

    def start(self) -> None:
        try:
            self.proc = subprocess.Popen(
                self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL)
        except FileNotFoundError as exc:
            raise ProviderUnavailableError(f"agent executable not found: {self.cmd[0]}") from exc
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            mid = msg.get("id")
            if mid in self._pending:
                self._pending[mid] = msg
            else:
                self._notifications.append(msg)

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.proc or not self.proc.stdin:
            raise BridgeError("FAB-TRANSPORT", "client not started")
        rid = next(_ids)
        self._pending[rid] = {}
        self.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": rid, "method": method,
                        "params": params or {}}).encode() + b"\n")
        self.proc.stdin.flush()
        import time
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            resp = self._pending.get(rid) or {}
            if resp:
                if "error" in resp:
                    e = resp["error"]
                    raise BridgeError(f"FAB-RPC-{e.get('code', 'ERR')}", str(e.get("message", e)))
                return resp.get("result", {})
            time.sleep(0.01)
        self._pending.pop(rid, None)
        raise BridgeError("FAB-TIMEOUT", f"{method} timed out after {self.timeout_s}s")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if self.proc and self.proc.stdin:
            self.proc.stdin.write(
                json.dumps({"jsonrpc": "2.0", "method": method,
                            "params": params or {}}).encode() + b"\n")
            self.proc.stdin.flush()

    def notifications(self) -> Iterator[dict[str, Any]]:
        while True:
            if self._notifications:
                yield self._notifications.pop(0)
            else:
                import time
                time.sleep(0.02)
                if self.proc and self.proc.poll() is not None and not self._notifications:
                    return

    # -- ACP semantics -------------------------------------------------------

    def initialize(self) -> dict[str, Any]:
        res = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "clientCapabilities": {"fs": {"readTextFile": True, "writeTextFile": True},
                                   "terminal": False}})
        self.protocol_version = res.get("protocolVersion", PROTOCOL_VERSION)
        return res

    def new_session(self, cwd: str = ".", mcp_servers: list[dict] | None = None) -> str:
        res = self.request("session/new", {"cwd": cwd, "mcpServers": mcp_servers or []})
        sid = res.get("sessionId")
        if not sid:
            raise BridgeError("FAB-SESSION", "session/new returned no sessionId")
        return str(sid)

    def prompt(self, session_id: str, text: str) -> dict[str, Any]:
        return self.request("session/prompt", {
            "sessionId": session_id,
            "prompt": [{"type": "text", "text": text}]})

    def cancel(self, session_id: str) -> None:
        self.notify("session/cancel", {"sessionId": session_id})

    def close(self) -> None:
        if self.proc:
            with _suppress_all():
                self.proc.terminate()
                self.proc.wait(timeout=3)
            if self.proc.poll() is None:
                self.proc.kill()
            self.proc = None


class _suppress_all:
    def __enter__(self): return None
    def __exit__(self, *a): return True
