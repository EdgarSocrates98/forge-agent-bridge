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
    orchs: dict[str, Any] = {}  # provider → orchestrator
    from .files import FileService
    from .metadata import SessionMetaStore
    meta = SessionMetaStore()
    files = FileService(Path.cwd())  # workspace root = bridge launch dir

    def _orch(provider: str) -> Any:
        from .orchestrator import build_orchestrator
        if provider not in orchs:
            orchs[provider] = build_orchestrator(provider)
        return orchs[provider]

    def _session_provider(sid: str, fallback: str = "fake") -> str:
        return str(meta.get(sid).get("provider") or fallback)

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
            body = self._body() if self.command in ("POST", "PUT", "PATCH") else {}
            if self.command == "GET" and parts == ["status"]:
                return self._send(200, {"ok": True,
                                        "workspace_root": str(files.root),
                                        "running": supervisor.running()})
            if self.command == "POST" and parts and parts[0] == "files":
                import base64

                from .adapter import BridgeError
                try:
                    act = parts[1] if len(parts) > 1 else ""
                    rel = str(body.get("path", "."))
                    if act == "list":
                        return self._send(200, {"items": files.list_dir(rel),
                                                "root": str(files.root)})
                    if act == "preview":
                        return self._send(200, files.preview(rel))
                    if act == "download":
                        return self._send(200, {
                            "path": rel,
                            "content_b64": base64.b64encode(
                                files.read_bytes(rel)).decode()})
                    if act == "upload":
                        data = base64.b64decode(body.get("content_b64", ""))
                        return self._send(200, files.upload(
                            rel, data, approved=bool(body.get("approved"))))
                    if act == "history":
                        return self._send(200, {"items": files.history(rel)})
                    if act == "restore":
                        return self._send(200, files.restore(
                            rel, str(body.get("version", "")),
                            approved=bool(body.get("approved"))))
                    return self._send(404, {"error": {"code": "FAB-404",
                                                    "message": "unknown file op"}})
                except BridgeError as e:
                    return self._send(403 if "FORBIDDEN" in e.code else 422,
                                      {"error": {"code": e.code,
                                                 "message": e.message}})
            if self.command == "GET" and parts == ["providers"]:
                from .registry import REGISTRY
                return self._send(200, {"items": [
                    d.model_dump(mode="json")
                    for d in REGISTRY.detect_all()]})
            if self.command == "POST" and parts == ["sessions"]:
                from .contracts import new_id
                sid = new_id("ses")
                cmd = body.get("cmd")
                if not isinstance(cmd, list) or not all(isinstance(c, str) for c in cmd):
                    return self._send(422, {"error": {"code": "FAB-VALIDATION",
                                                    "message": "cmd must be a string list"}})
                supervisor.spawn(sid, cmd, cwd=body.get("cwd", "."))
                return self._send(201, {"session_id": sid})
            if self.command == "POST" and parts == ["agent-sessions"]:
                provider = str(body.get("provider", "fake"))
                try:
                    s = _orch(provider).create_session(
                        product_id=body.get("product_id"),
                        workspace_id=body.get("workspace_id"),
                        mcp_servers=body.get("mcp_servers"))
                    meta.upsert(s.id, provider=provider,
                                product_id=s.product_id,
                                workspace_id=s.workspace_id,
                                title=body.get("title") or "")
                    out = s.model_dump(mode="json")
                    out["meta"] = meta.get(s.id)
                    return self._send(201, out)
                except Exception as e:  # noqa: BLE001 — adapter errors vary; map to typed envelope
                    code = getattr(e, "code", "FAB-ERROR")
                    return self._send(502, {"error": {"code": code,
                                                    "message": str(e)}})
            if self.command == "GET" and parts == ["agent-sessions"]:
                store = meta.list(include_archived=True)
                live: dict[str, Any] = {}
                for o in orchs.values():
                    for s in o.list_sessions():
                        d = s.model_dump(mode="json")
                        d["meta"] = store.get(s.id, {})
                        live[s.id] = d
                for sid, m in store.items():
                    if sid not in live:
                        live[sid] = {"id": sid, "state": "closed",
                                     "provider": m.get("provider"),
                                     "meta": m}
                return self._send(200, {"items": list(live.values())})
            if len(parts) == 2 and parts[0] == "agent-sessions":
                sid = parts[1]
                if self.command == "PATCH":
                    allowed = {k: v for k, v in body.items() if k in
                               {"title", "product_id", "workspace_id",
                                "favorite", "archived", "visibility", "notes"}}
                    return self._send(200, {"meta": meta.upsert(sid, **allowed)})
                if self.command == "DELETE":
                    provider = _session_provider(sid)
                    closed = False
                    if provider in orchs:
                        try:
                            orchs[provider].close(sid)
                            closed = True
                        except Exception as e:  # noqa: BLE001
                            self.log_message("close failed: %s", e)
                    meta.upsert(sid, archived=True)
                    return self._send(200, {"closed": closed, "archived": True})
            if len(parts) == 3 and parts[0] == "agent-sessions":
                sid, action = parts[1], parts[2]
                provider = body.get("provider") or _session_provider(sid)
                try:
                    o = _orch(provider)
                    if action == "prompt" and self.command == "POST":
                        text = str(body.get("text", ""))
                        if not text:
                            return self._send(422, {"error": {"code": "FAB-VALIDATION",
                                                            "message": "text required"}})
                        o.prompt(sid, text,
                                 attachments=body.get("attachments"))
                        o.drain(sid)
                        return self._send(200, {"accepted": True})
                    if action == "events" and self.command == "POST":
                        after = int(body.get("after_seq", 0))
                        return self._send(200, {"items": o.replay(sid, after)})
                    if action == "cancel" and self.command == "POST":
                        o.cancel(sid)
                        return self._send(200, {"cancelled": True})
                    if action == "resume" and self.command == "POST":
                        ref = str(body.get("session_ref") or "")
                        if not ref:
                            return self._send(422, {"error": {"code": "FAB-VALIDATION",
                                                            "message": "session_ref required"}})
                        s = o.resume(ref)
                        meta.upsert(s.id, provider=provider)
                        return self._send(201, s.model_dump(mode="json"))
                    if action == "approve" and self.command == "POST":
                        o.approve(sid, str(body.get("approval_id", "")),
                                  bool(body.get("approved")))
                        return self._send(200, {"resolved": True})
                    if action == "artifacts" and self.command == "POST":
                        return self._send(200, {"items": o.artifacts(sid)})
                except Exception as e:  # noqa: BLE001 — adapter errors vary; map to typed envelope
                    code = getattr(e, "code", "FAB-ERROR")
                    return self._send(502, {"error": {"code": code,
                                                    "message": str(e)}})
            if len(parts) == 2 and parts[0] == "sessions" and self.command == "DELETE":
                ok = supervisor.terminate(parts[1])
                return self._send(200 if ok else 404, {"terminated": ok})
            return self._send(404, {"error": {"code": "FAB-404",
                                            "message": "not found"}})

        do_GET = _route
        do_POST = _route
        do_PATCH = _route
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
