"""Local Bridge (§19.5) — secure local service + process supervisor + pairing.

The bridge runs on 127.0.0.1 ONLY (never a public interface). Pairing
issues a bearer token into a state file readable only by the local user;
every HTTP call requires it. Agent processes are supervised: tracked,
terminable, cleaned on shutdown.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / ".forge-bridge"


def state_dir() -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR


def pair_token() -> str:
    """Issue/persist a local pairing token (0600). Idempotent."""
    f = state_dir() / "pair.token"
    if f.exists():
        return f.read_text().strip()
    tok = secrets.token_urlsafe(32)
    f.write_text(tok)
    os.chmod(f, 0o600)
    return tok


class ProcessSupervisor:
    """Tracks spawned agent processes; guarantees cleanup."""

    def __init__(self) -> None:
        self._procs: dict[str, subprocess.Popen[bytes]] = {}
        self._lock = threading.Lock()

    def spawn(self, sid: str, cmd: list[str], cwd: str = ".") -> subprocess.Popen[bytes]:
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True)  # own process group → clean kill
        with self._lock:
            self._procs[sid] = proc
        return proc

    def terminate(self, sid: str, timeout_s: float = 3.0) -> bool:
        with self._lock:
            proc = self._procs.pop(sid, None)
        if not proc:
            return False
        with contextlib.suppress(ProcessLookupError, OSError):
            os.killpg(proc.pid, signal.SIGTERM)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=timeout_s)
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError, OSError):
                os.killpg(proc.pid, signal.SIGKILL)
        return True

    def terminate_all(self) -> None:
        for sid in list(self._procs):
            self.terminate(sid)

    def running(self) -> list[str]:
        return [s for s, p in self._procs.items() if p.poll() is None]

    def __len__(self) -> int:
        return len(self._procs)


def make_app() -> Any:
    """Local bridge HTTP service (stdlib; auth-gated). Endpoints:
    GET /status · GET /providers · POST /pair · POST /sessions ·
    POST /sessions/{id}/prompt · DELETE /sessions/{id}."""
    from http.server import BaseHTTPRequestHandler

    token = pair_token()
    supervisor = ProcessSupervisor()

    class H(BaseHTTPRequestHandler):
        def _auth_ok(self) -> bool:
            return self.headers.get("Authorization") == f"Bearer {token}"

        def _send(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict[str, Any]:
            n = int(self.headers.get("Content-Length") or 0)
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return {}

        def _route(self) -> None:
            if not self._auth_ok():
                return self._send(401, {"error": {"code": "FAB-UNAUTHORIZED",
                                                "message": "bearer required"}})
            parts = [p for p in self.path.split("/") if p]
            if self.command == "GET" and parts == ["status"]:
                return self._send(200, {"ok": True,
                                        "running": supervisor.running()})
            if self.command == "GET" and parts == ["providers"]:
                from .registry import REGISTRY
                return self._send(200, {"items": [
                    d.model_dump(mode="json")
                    for d in REGISTRY.detect_all()]})
            if self.command == "POST" and parts == ["sessions"]:
                from .contracts import new_id
                body = self._body()
                sid = new_id("ses")
                cmd = body.get("cmd")
                if not isinstance(cmd, list) or not all(isinstance(c, str) for c in cmd):
                    return self._send(422, {"error": {"code": "FAB-VALIDATION",
                                                    "message": "cmd must be a string list"}})
                supervisor.spawn(sid, cmd, cwd=body.get("cwd", "."))
                return self._send(201, {"session_id": sid})
            if len(parts) == 2 and parts[0] == "sessions" and self.command == "DELETE":
                ok = supervisor.terminate(parts[1])
                return self._send(200 if ok else 404, {"terminated": ok})
            return self._send(404, {"error": {"code": "FAB-404",
                                            "message": "not found"}})

        do_GET = _route
        do_POST = _route
        do_DELETE = _route

        def log_message(self, *a: Any) -> None:  # quiet — logs via file
            pass

    return H, supervisor


def serve(port: int = 8471) -> None:
    from http.server import ThreadingHTTPServer
    handler, supervisor = make_app()
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)  # localhost only
    try:
        srv.serve_forever()
    finally:
        supervisor.terminate_all()
