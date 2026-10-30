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
import time
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .adapter import BridgeError

STATE_DIR = Path.home() / ".forge-bridge"
MAX_BODY = 8 * 1024 * 1024          # 8 MiB request cap (§25.5)
RATE_LIMIT = 240                    # req/min per credential (§25.5)
NONCE_WINDOW_S = 60.0               # replay window for X-FAB-Nonce
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
# §30.1 — full-origin allowlist: exact "scheme://host:port" entries may be
# configured via FAB_ALLOWED_ORIGINS (comma-separated) or established by
# pairing. Default policy additionally accepts http(s) loopback origins
# (scheme http/https + loopback host); everything else is rejected.
_ALLOWED_ORIGINS: set[str] = {
    o.strip() for o in os.environ.get("FAB_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
}


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
    """Tracks spawned agent processes; guarantees cleanup.

    §28.4 platform lifecycle:
    - POSIX: `start_new_session` → own process group → `killpg` SIGTERM,
      SIGKILL fallback. Verified on Linux/macOS.
    - Windows: no process groups — `CREATE_NEW_PROCESS_GROUP` +
      `proc.terminate()` (WM_CLOSE/TerminateProcess), then taskkill /T /F
      for the tree. Job Objects are the stronger seam (kill-on-close) but
      require pywin32 — flagged unverified until exercised on Windows CI.
    """

    IS_WINDOWS = os.name == "nt"

    def __init__(self) -> None:
        self._procs: dict[str, subprocess.Popen[bytes]] = {}
        self._lock = threading.Lock()

    def spawn(self, sid: str, cmd: list[str], cwd: str = ".") -> subprocess.Popen[bytes]:
        kwargs: dict[str, Any] = {}
        if self.IS_WINDOWS:
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
                | subprocess.CREATE_NO_WINDOW)       # type: ignore[attr-defined]
        else:
            kwargs["start_new_session"] = True      # own pgrp → clean kill
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, **kwargs)
        with self._lock:
            self._procs[sid] = proc
        return proc

    def terminate(self, sid: str, timeout_s: float = 3.0) -> bool:
        with self._lock:
            proc = self._procs.pop(sid, None)
        if not proc:
            return False
        if self.IS_WINDOWS:
            return self._terminate_windows(proc, timeout_s)
        with contextlib.suppress(ProcessLookupError, OSError):
            os.killpg(proc.pid, signal.SIGTERM)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=timeout_s)
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError, OSError):
                os.killpg(proc.pid, signal.SIGKILL)
        return True

    @staticmethod
    def _terminate_windows(proc: subprocess.Popen[bytes],
                           timeout_s: float) -> bool:
        """Windows: graceful terminate → taskkill /T /F for the tree."""
        with contextlib.suppress(OSError):
            proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=timeout_s)
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True, timeout=timeout_s, check=False)
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
    from .approvals import ApprovalStore
    from .broker import Broker
    from .budgets import BudgetLedger
    from .collab import AuditLog, CollabStore
    from .files import FileService
    from .metadata import SessionMetaStore
    from .pairing import Pairing
    from .runners import RunnerRegistry
    meta = SessionMetaStore()
    files = FileService(Path.cwd())  # workspace root = bridge launch dir
    runners = RunnerRegistry()
    budgets = BudgetLedger()
    collab = CollabStore()
    audit = AuditLog()
    pairing = Pairing(token)
    approvals = ApprovalStore()
    broker = Broker()
    from .context import ContextStore, MCPFederation
    from .events import DurableEventStore, seq_floor
    ctxs = ContextStore()
    mcp_fed = MCPFederation()
    event_store = DurableEventStore(state_dir() / "events")
    # seq continuity across restarts — resume above max persisted seq
    _max_seq = 0
    for _f in event_store.root.glob("*.jsonl"):
        with contextlib.suppress(Exception):
            for _ln in _f.read_text().splitlines():
                if _ln.strip():
                    _max_seq = max(_max_seq, int(json.loads(_ln).get("seq", 0)))
    seq_floor(_max_seq)
    rl_window: dict[str, deque[float]] = {}
    seen_nonces: dict[str, float] = {}

    def _principal(auth: dict[str, Any], sid: str,
                   headers: Any) -> str:
        """Identity comes from the *authenticated* credential — never the
        self-declared header alone. Master token (local admin) may assert a
        principal for dev; session tokens act as their device name."""
        if auth.get("kind") == "session":
            return str(auth.get("actor"))
        return collab.principal(sid, headers.get("X-FAB-Principal"))

    def _scope_map(sid: str, provider: str, principal: str) -> dict[str, str]:
        m = meta.get(sid)
        return {"user": principal, "session": sid, "provider": provider,
                "workspace": str(m.get("workspace_id") or ""),
                "product": str(m.get("product_id") or "")}

    def _orch(provider: str) -> Any:
        from .orchestrator import build_orchestrator
        if provider not in orchs:
            orchs[provider] = build_orchestrator(provider, store=event_store)
        return orchs[provider]

    def _session_provider(sid: str, fallback: str = "fake") -> str:
        return str(meta.get(sid).get("provider") or fallback)

    class H(BaseHTTPRequestHandler):
        timeout = 30  # socket read timeout (§25.5 request timeout)

        def _auth(self) -> dict[str, Any] | None:
            """Master pair token OR a paired session token (hashed compare)."""
            h = self.headers.get("Authorization", "")
            if not h.startswith("Bearer "):
                return None
            try:
                return pairing.authenticate(h[7:].strip())
            except BridgeError:
                return None

        def _origin_ok(self) -> bool:
            origin = self.headers.get("Origin")
            if not origin:
                return True  # non-browser client — no Origin to check
            if origin in _ALLOWED_ORIGINS:
                return True
            try:
                p = urlparse(origin)
            except ValueError:
                return False          # malformed origin
            if p.scheme not in {"http", "https"}:
                return False          # non-web schemes rejected
            if not p.hostname or p.hostname not in _ALLOWED_HOSTS:
                return False          # external host / DNS rebinding guard
            return p.port is None or 0 < p.port < 65536

        def _sse(self, orch: Any, sid: str, after_seq: int,
                 *, max_seconds: float = 55.0, heartbeat_s: float = 10.0
                 ) -> None:
            """Server-Sent Events stream (§26.6).

            Ordered, deduplicated by seq, resumable via Last-Event-ID or
            ?after_seq=, heartbeat comments keep proxies alive, bounded
            duration so clients reconnect with their cursor (gap-free).
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            last = after_seq
            start = time.monotonic()
            last_beat = start
            try:
                while time.monotonic() - start < max_seconds:
                    for ev in orch.replay(sid, last):
                        seq = int(ev.get("seq", 0))
                        if seq <= last:
                            continue          # dedup
                        last = seq
                        data = json.dumps(ev, separators=(",", ":"))
                        self.wfile.write(
                            f"id: {seq}\nevent: {ev['type']}\n"
                            f"data: {data}\n\n".encode())
                    now = time.monotonic()
                    if now - last_beat >= heartbeat_s:
                        self.wfile.write(b": hb\n\n")
                        last_beat = now
                    self.wfile.flush()
                    time.sleep(0.25)
            except (BrokenPipeError, ConnectionResetError):
                return  # client disconnected — cursor resumes cleanly

        def _send(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            origin = self.headers.get("Origin")
            if origin and self._origin_ok():
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict[str, Any]:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise BridgeError("FAB-TOO-LARGE",
                                  f"body exceeds {MAX_BODY} bytes")
            raw = self.rfile.read(n) or b"{}"
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                raise BridgeError("FAB-VALIDATION", "malformed JSON body") from None
            if not isinstance(data, dict):
                raise BridgeError("FAB-VALIDATION", "JSON body must be an object")
            return data

        def do_OPTIONS(self) -> None:  # CORS preflight (§25.5)
            if not self._origin_ok():
                return self._send(403, {"error": {
                    "code": "FAB-FORBIDDEN", "message": "origin rejected"}})
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin",
                             self.headers.get("Origin", ""))
            self.send_header("Access-Control-Allow-Methods",
                             "GET, POST, PATCH, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers",
                             "Authorization, Content-Type, "
                             "X-FAB-Principal, X-FAB-Nonce")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")
            self.end_headers()

        def _host_ok(self) -> bool:
            """DNS-rebinding guard: Host must be loopback (§25.5)."""
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in _ALLOWED_HOSTS

        def _rate_ok(self, cred: str) -> bool:
            now = time.time()
            w = rl_window.setdefault(cred, deque())
            while w and now - w[0] > 60.0:
                w.popleft()
            if len(w) >= RATE_LIMIT:
                return False
            w.append(now)
            return True

        def _replay_ok(self) -> bool:
            nonce = self.headers.get("X-FAB-Nonce")
            if not nonce:
                return True
            now = time.time()
            for k, ts in list(seen_nonces.items()):
                if now - ts > NONCE_WINDOW_S:
                    del seen_nonces[k]
            if nonce in seen_nonces:
                return False
            seen_nonces[nonce] = now
            return True

        def _route(self) -> None:
            if not self._host_ok():
                return self._send(403, {"error": {
                    "code": "FAB-FORBIDDEN",
                    "message": "host rejected (loopback only)"}})
            auth = self._auth()
            cred = (auth or {}).get("actor") or self.headers.get(
                "Authorization", "")[-16:]
            if not self._rate_ok(cred):
                return self._send(429, {"error": {
                    "code": "FAB-RATE-LIMIT", "message": "rate limit"}})
            if not self._replay_ok():
                return self._send(409, {"error": {
                    "code": "FAB-REPLAY", "message": "nonce replay"}})
            if not self._origin_ok():
                return self._send(403, {"error": {
                    "code": "FAB-FORBIDDEN", "message": "origin rejected"}})
            parts = [p for p in urlparse(self.path).path.split("/") if p]
            # -- unauthenticated pairing exchange (localhost only) ---------
            if parts == ["pair", "exchange"] and self.command == "POST":
                try:
                    b = self._body()
                    out = pairing.exchange(
                        str(b.get("pair_token", "")),
                        str(b.get("device_name", "")),
                        tuple(b.get("scopes") or ("agent",)))
                    return self._send(201, out)
                except BridgeError as e:
                    return self._send(403 if "FORBIDDEN" in e.code else 422,
                                      {"error": {"code": e.code,
                                                 "message": e.message}})
            if auth is None:
                return self._send(401, {"error": {"code": "FAB-UNAUTHORIZED",
                                                "message": "bearer required"}})
            body: dict[str, Any] = {}
            if self.command in ("POST", "PATCH"):
                try:
                    body = self._body()
                except BridgeError as e:
                    code = e.code
                    return self._send(
                        413 if "TOO-LARGE" in code else 422,
                        {"error": {"code": code, "message": e.message}})
            if self.command == "GET" and parts == ["status"]:
                return self._send(200, {"ok": True,
                                        "workspace_root": str(files.root),
                                        "running": supervisor.running()})
            if self.command == "POST" and parts and parts[0] == "files":
                import base64

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
                    if act in ("upload", "restore"):
                        # §25.4 — mutating file ops need a bound approval
                        # token whose args digest matches this exact call.
                        op_args = ({"path": rel,
                                    "content_b64": body.get(
                                        "content_b64", "")}
                                   if act == "upload"
                                   else {"path": rel,
                                         "version": str(
                                             body.get("version", ""))})
                        tok = str(body.get("approval_token", ""))
                        broker.authorize(
                            actor=auth, op=f"files:{act}",
                            resource=f"file:{rel}",
                            session_id=str(body.get("session_id", "")),
                            tool="files")
                        if not tok:
                            req = approvals.request(
                                session_id=str(body.get("session_id", "")),
                                actor=auth.get("actor", "local"),
                                resource=f"file:{rel}", action=act,
                                args=op_args, risk="high")
                            return self._send(409, {"error": {
                                "code": "FAB-APPROVAL-REQUIRED",
                                "message": "approval required"},
                                "approval_request": req})
                        approvals.consume(
                            tok, session_id=str(body.get("session_id", "")),
                            resource=f"file:{rel}", action=act, args=op_args)
                        if act == "upload":
                            data = base64.b64decode(
                                body.get("content_b64", ""))
                            return self._send(200, files.upload(
                                rel, data, approved=True))
                        return self._send(200, files.restore(
                            rel, str(body.get("version", "")),
                            approved=True))
                    if act == "history":
                        return self._send(200, {"items": files.history(rel)})
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
            # -- runners (§23.1) ------------------------------------------------
            if parts and parts[0] == "runners":
                if self.command == "GET":
                    return self._send(200, {"items": runners.list()})
                if self.command == "POST" and len(parts) == 1:
                    try:
                        from .ssrf import validate_runner_url
                        endpoint = body.get("endpoint")
                        if endpoint:
                            endpoint = validate_runner_url(
                                str(endpoint),
                                allow_loopback=bool(
                                    body.get("allow_loopback")))
                        r = runners.register(
                            str(body["id"]), str(body.get("kind", "remote")),
                            endpoint=endpoint,
                            labels=body.get("labels"),
                            quota_sessions=int(body.get("quota_sessions", 8)))
                        audit.emit("runner.register",
                                   auth.get("actor", "local"),
                                   runner=r["id"], kind=r["kind"])
                        return self._send(201, r)
                    except Exception as e:  # noqa: BLE001
                        code = getattr(e, "code", "FAB-ERROR")
                        return self._send(422, {"error": {"code": code,
                                                        "message": str(e)}})
                if len(parts) == 3 and parts[2] == "health" and self.command == "POST":
                    try:
                        r = next((x for x in runners.list()
                                  if x["id"] == parts[1]), None)
                        if r is None:
                            raise BridgeError("FAB-NOT-FOUND",
                                              "unknown runner")
                        if r.get("endpoint"):
                            from .ssrf import probe
                            r["state"] = probe(str(r["endpoint"]),
                                               parts[1])["state"]
                            return self._send(200, r)
                        return self._send(200, runners.health(parts[1]))
                    except Exception as e:  # noqa: BLE001
                        return self._send(404, {"error": {
                            "code": getattr(e, "code", "FAB-ERROR"),
                            "message": str(e)}})
                if len(parts) == 3 and parts[2] == "deregister" \
                        and self.command == "POST":
                    try:
                        ok = runners.deregister(parts[1])
                    except Exception as e:  # noqa: BLE001
                        return self._send(422, {"error": {
                            "code": getattr(e, "code", "FAB-ERROR"),
                            "message": str(e)}})
                    audit.emit("runner.deregister",
                               auth.get("actor", "local"),
                               runner=parts[1])
                    return self._send(200 if ok else 404, {"drained": ok})
            # -- budgets (§23.4) ------------------------------------------------
            if parts and parts[0] == "budget":
                if self.command == "GET":
                    return self._send(200, budgets.summary())
                if self.command == "POST" and len(parts) == 2 \
                        and parts[1] == "limits":
                    try:
                        lim = budgets.set_limit(
                            str(body["scope"]), str(body["key"]),
                            str(body["window"]), int(body["tokens"]))
                        audit.emit("budget.limit",
                                   auth.get("actor", "local"), **lim)
                        return self._send(201, lim)
                    except Exception as e:  # noqa: BLE001
                        code = getattr(e, "code", "FAB-ERROR")
                        return self._send(422, {"error": {"code": code,
                                                        "message": str(e)}})
            # -- pairing management (§25.6) ------------------------------------
            if parts and parts[0] == "pair":
                if self.command == "POST" and parts == ["pair", "rotate"]:
                    try:
                        out = pairing.rotate(str(body.get("pair_token", "")))
                        return self._send(200, out)
                    except BridgeError as e:
                        return self._send(
                            403 if "FORBIDDEN" in e.code else 422,
                            {"error": {"code": e.code,
                                       "message": e.message}})
                if self.command == "GET" and parts == ["pair", "devices"]:
                    return self._send(200, {"items": pairing.devices()})
                if (self.command == "DELETE" and len(parts) == 3
                        and parts[1] == "devices"):
                    ok = pairing.revoke_device(parts[2])
                    audit.emit("pair.revoke", auth.get("actor", "local"),
                               device=parts[2])
                    return self._send(200 if ok else 404, {"revoked": ok})
            # -- approval tokens (§25.4) ----------------------------------------
            if parts and parts[0] == "approvals":
                if self.command == "GET":
                    sid = str(body.get("session_id", "")) or \
                        self.path.split("session_id=")[-1] \
                        if "session_id=" in self.path else ""
                    return self._send(200, {
                        "items": approvals.pending_for(sid)})
                if (self.command == "POST" and len(parts) == 3
                        and parts[2] == "resolve"):
                    try:
                        out = approvals.resolve(
                            parts[1],
                            approved=bool(body.get("approved")),
                            actor=auth.get("actor", "local"))
                        audit.emit("approval.resolve",
                                   auth.get("actor", "local"),
                                   approval_id=parts[1],
                                   approved=bool(body.get("approved")))
                        return self._send(200, out)
                    except BridgeError as e:
                        return self._send(
                            403 if "FORBIDDEN" in e.code else 404,
                            {"error": {"code": e.code,
                                       "message": e.message}})
            # -- audit trail (§23.2) --------------------------------------------
            # ---- Part IX: deterministic intelligence (read-only) --------
            if parts and parts[0] == "intel":
                from . import intelligence as intel
                from .registry import REGISTRY
                provs = [d.model_dump(mode="json")
                         for d in REGISTRY.detect_all()]
                if self.command == "POST" and parts == ["intel", "route"]:
                    return self._send(200, intel.route_provider(
                        provs,
                        task_type=str(body.get("task_type", "chat")),
                        required=body.get("required"),
                        privacy=str(body.get("privacy", "local-ok")),
                        prefer=body.get("prefer"),
                        max_cost_usd=body.get("max_cost_usd")))
                if len(parts) == 3 and self.command == "GET":
                    sid, sub = parts[1], parts[2]
                    collab.assert_can_read(
                        sid, collab.principal(
                            sid, self.headers.get("X-FAB-Principal")))
                    evs = event_store.replay(sid)
                    ctx = ctxs.get(sid)
                    if sub == "quality":
                        return self._send(200, intel.evaluate_session(evs))
                    if sub == "context-health":
                        return self._send(200, intel.context_health(ctx))
                    if sub == "replay":
                        return self._send(200, intel.replay_detail(evs, ctx))
                    if sub == "decisions":
                        pid = (ctx or {}).get("product_id") or ""
                        return self._send(200, {"items": intel.decision_records(
                            evs, sid, pid)})
                    if sub == "integrity":
                        from .integrity import check_session
                        from .registry import REGISTRY
                        return self._send(200, check_session(
                            sid, events=evs, meta=meta.get(sid),
                            pending_approvals=approvals.pending_for(sid),
                            known_providers={
                                d.name for d in REGISTRY.detect_all()}))
                if self.command == "GET" and parts == ["intel", "finops"]:
                    return self._send(200, intel.finops_report(
                        budgets.summary()))
                if self.command == "GET" and parts == ["intel", "mode"]:
                    return self._send(200, intel.degraded_mode(provs))
                if self.command == "GET" and parts == ["intel", "workspace"]:
                    return self._send(200, intel.workspace_summary(
                        meta.list(include_archived=True),
                        {s: c for s in meta.list(include_archived=True)
                         if (c := ctxs.get(s))},
                        mcp_fed.list(), budgets.limits()))
                return self._send(404, {"error": {"code": "FAB-NOT-FOUND",
                                                "message": "intel route"}})
            # ---- Cycle 28.6: backup/restore (no secrets) -----------------
            if parts and parts[0] == "backup":
                from .backup import create_backup, restore_backup
                if self.command == "POST" and len(parts) == 1:
                    m = create_backup(state_dir())
                    audit.emit("backup.create", auth.get("actor", "local"),
                               files=len(m["files"]),
                               excluded=len(m["excluded"]))
                    return self._send(201, {"backup": m["out"],
                                            "files": len(m["files"]),
                                            "excluded": m["excluded"]})
                if (self.command == "POST" and len(parts) == 2
                        and parts[1] == "restore"):
                    src = Path(str(body.get("path", "")))
                    if not src.is_file():
                        return self._send(422, {"error": {
                            "code": "FAB-VALIDATION",
                            "message": "backup path required"}})
                    actor = auth.get("actor", "local")
                    args = {"path": str(src)}
                    # one-time approval token: retry with it to execute
                    if body.get("approval_token"):
                        approvals.consume(
                            str(body["approval_token"]),
                            session_id="backup", resource=str(src),
                            action="restore", args=args)
                        audit.emit("backup.restore", actor, backup=str(src))
                        return self._send(200, {
                            "restore": restore_backup(src, state_dir())})
                    req = approvals.request(
                        session_id="backup", actor=actor,
                        resource=str(src), action="restore", args=args,
                        scope="workspace", risk="high")
                    return self._send(200, {"restore": "approval-required",
                                            "approval_request": req})
                return self._send(404, {"error": {"code": "FAB-NOT-FOUND",
                                                "message": "backup route"}})
            # ---- Cycle 27: context federation + MCP registry ------------
            if parts and parts[0] == "mcp":
                if self.command == "GET" and len(parts) == 1:
                    return self._send(200, {"items": mcp_fed.list()})
                if self.command == "POST" and len(parts) == 1:
                    from .context import MCPServerDescriptor
                    d = MCPServerDescriptor.model_validate(body)
                    audit.emit("mcp.register", auth.get("actor", "local"),
                               server_id=d.server_id)
                    return self._send(201, mcp_fed.register(d))
                if len(parts) == 3 and parts[2] == "health" \
                        and self.command == "POST":
                    return self._send(200, mcp_fed.set_health(
                        parts[1], str(body.get("health", "unverified"))))
                return self._send(404, {"error": {"code": "FAB-NOT-FOUND",
                                                "message": "mcp route"}})
            if parts and parts[0] == "context":
                from .context import AgentContextDelta, ProductAgentSessionContext
                if self.command == "POST" and parts == ["context", "draft"]:
                    # §27.2 — minimal context package for a product binding
                    ctx = ProductAgentSessionContext.model_validate({
                        **(body or {}),
                        "identity": auth.get("actor", "local")})
                    return self._send(200, {
                        "context": ctx.model_dump(mode="json", by_alias=True)})
                if self.command == "POST" and parts == ["context", "attach"]:
                    sid = str(body.get("session_id") or "")
                    ctx = ProductAgentSessionContext.model_validate(
                        body.get("context") or {})
                    ctxs.bind(sid, ctx)
                    meta.upsert(sid, context_version=ctx.context_version,
                                policy_version=ctx.policy_version)
                    audit.emit("context.attach", auth.get("actor", "local"),
                               session=sid,
                               context_version=ctx.context_version)
                    return self._send(200, {"bound": True})
                if (self.command == "POST" and len(parts) == 2
                        and parts[1] == "delta"):
                    d = AgentContextDelta.model_validate({
                        **(body or {}),
                        "reviewer": auth.get("actor", "local")})
                    ctxs.record_delta(d)
                    audit.emit("context.delta", auth.get("actor", "local"),
                               session=d.session_id, review=d.review)
                    return self._send(201, {"recorded": True,
                                            "review": d.review})
                if (self.command == "POST" and len(parts) == 2
                        and parts[1] == "revoke"):
                    sid = str((body or {}).get("session_id", ""))
                    revoked = ctxs.revoke(sid)
                    audit.emit("context.revoked", auth.get("actor", "local"),
                               session=sid,
                               context_version=revoked.get("context_version"))
                    return self._send(200, {"revoked": True, "session_id": sid})
                if (self.command == "GET" and len(parts) == 2
                        and parts[1] == "deltas"):
                    qs = parse_qs(urlparse(self.path).query)
                    return self._send(200, {"items": ctxs.deltas(
                        product_id=(qs.get("product_id") or [None])[0],
                        review=(qs.get("review") or [None])[0])})
                return self._send(404, {"error": {"code": "FAB-NOT-FOUND",
                                                "message": "context route"}})
            if self.command == "GET" and parts == ["audit"]:
                return self._send(200, {"items": audit.tail(
                    int(self.headers.get("X-Tail", "50")))})
            if self.command == "POST" and parts == ["sessions"]:
                # §25.2 — typed ops only; the client never supplies argv.
                op = str(body.get("op", ""))
                if op != "spawn-provider":
                    return self._send(422, {"error": {
                        "code": "FAB-VALIDATION",
                        "message": "op must be 'spawn-provider'"}})
                provider = str(body.get("provider", ""))
                try:
                    o = _orch(provider)
                    argv = list(getattr(o.adapter, "SPAWN_ARGV",
                                        [getattr(o.adapter, "EXE",
                                                 provider)]))
                except Exception as e:  # noqa: BLE001 — adapter init varies
                    return self._send(422, {"error": {
                        "code": getattr(e, "code", "FAB-VALIDATION"),
                        "message": f"unknown provider {provider!r}"}})
                from .contracts import new_id
                sid = new_id("ses")
                supervisor.spawn(sid, argv, cwd=body.get("cwd", "."))
                return self._send(201, {"session_id": sid,
                                        "provider": provider})
            if self.command == "POST" and parts == ["agent-sessions"]:
                provider = str(body.get("provider", "fake"))
                try:
                    runner = body.get("runner") or "local"
                    local_load = sum(
                        len(o.sessions) for o in orchs.values())
                    runners.place(runner, local_load=local_load)
                    s = _orch(provider).create_session(
                        product_id=body.get("product_id"),
                        workspace_id=body.get("workspace_id"),
                        mcp_servers=body.get("mcp_servers"))
                    meta.upsert(s.id, provider=provider,
                                product_id=s.product_id,
                                workspace_id=s.workspace_id,
                                title=body.get("title") or "")
                    collab.share(s.id,
                                 owner=_principal(auth, s.id, self.headers),
                                 visibility=body.get("visibility", "private"))
                    # §27.1 — bind forge/ProductAgentSessionContext/v1
                    from .context import ProductAgentSessionContext
                    sc = body.get("context") or {}
                    sc_ctx = ProductAgentSessionContext.model_validate({
                        **sc,
                        "identity": _principal(auth, s.id, self.headers),
                        "provider": provider,
                        "product_id": sc.get("product_id") or s.product_id,
                        "workspace_id": sc.get("workspace_id") or s.workspace_id,
                    })
                    ctxs.bind(s.id, sc_ctx)
                    # §27.5 — requested MCP servers are filtered through the
                    # federated registry + context allowlist (honest denial)
                    req_mcp = body.get("mcp_servers") or []
                    denied_mcp = [m for m in req_mcp
                                  if not mcp_fed.allowed_for(sc_ctx, m)]
                    meta.upsert(s.id, context_version=sc_ctx.context_version,
                                policy_version=sc_ctx.policy_version)
                    audit.emit("session.create",
                               auth.get("actor", "local"),
                               session=s.id, provider=provider,
                               runner=runner,
                               context_version=sc_ctx.context_version)
                    out = s.model_dump(mode="json")
                    out["meta"] = meta.get(s.id)
                    out["context"] = sc_ctx.model_dump(mode="json",
                                                       by_alias=True)
                    if denied_mcp:
                        out["mcp_denied"] = denied_mcp
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
                    principal = _principal(auth, sid, self.headers)
                    if action == "prompt" and self.command == "POST":
                        text = str(body.get("text", ""))
                        if not text:
                            return self._send(422, {"error": {"code": "FAB-VALIDATION",
                                                            "message": "text required"}})
                        broker.authorize(
                            actor=auth, op="prompt",
                            resource=f"agent-session:{sid}",
                            session_id=sid,
                            product_id=str(
                                meta.get(sid).get("product_id") or ""),
                            workspace_id=str(
                                meta.get(sid).get("workspace_id") or ""),
                            principal=principal, collab=collab)
                        ctxs.assert_allowed(sid)  # §27.6 context gate
                        budgets.check(_scope_map(sid, provider, principal))
                        o.prompt(sid, text,
                                 attachments=body.get("attachments"))
                        n = o.drain(sid)
                        # record real token usage from usage.updated events
                        evs = o.replay(sid)
                        tin = sum(int(e["payload"].get("tokens_in") or 0)
                                  for e in evs if e["type"] == "usage.updated")
                        tout = sum(int(e["payload"].get("tokens_out") or 0)
                                   for e in evs if e["type"] == "usage.updated")
                        if tin or tout:
                            budgets.record(
                                _scope_map(sid, provider, principal),
                                tin, tout,
                                estimated=not any(
                                    e["type"] == "usage.updated" for e in evs))
                        return self._send(200, {"accepted": True,
                                                "events_drained": n})
                    if action == "events" and self.command == "POST":
                        after = int(body.get("after_seq", 0))
                        return self._send(200, {"items": o.replay(sid, after)})
                    if action == "stream" and self.command == "GET":
                        # §26.6 — SSE: ordered, deduped by seq, cursor via
                        # Last-Event-ID or ?after_seq=, heartbeats, reconnect
                        collab.assert_can_read(sid, principal)
                        qs = parse_qs(urlparse(self.path).query)
                        after = int(qs.get("after_seq", [0])[0] or 0)
                        last_id = self.headers.get("Last-Event-ID")
                        if last_id:
                            after = int(last_id)
                        return self._sse(o, sid, after)
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
                        collab.assert_can_approve(sid, principal)
                        o.approve(sid, str(body.get("approval_id", "")),
                                  bool(body.get("approved")))
                        audit.emit("session.approve", principal,
                                   session=sid,
                                   approval_id=body.get("approval_id"),
                                   approved=bool(body.get("approved")))
                        return self._send(200, {"resolved": True})
                    if action == "share" and self.command == "POST":
                        collab.assert_can_act(sid, principal)
                        rec = collab.share(
                            sid, owner=principal,
                            visibility=str(body.get("visibility", "private")),
                            observers=body.get("observers"),
                            delegated_to=body.get("delegated_to"))
                        audit.emit("session.share", principal, session=sid,
                                   visibility=rec["visibility"])
                        return self._send(200, {"collab": rec})
                    if action == "comment" and self.command == "POST":
                        rec = collab.comment(
                            sid, principal, str(body.get("text", "")))
                        return self._send(200, {"comments": rec["comments"]})
                    if action == "handoff" and self.command == "POST":
                        return self._handoff(sid, provider, o, principal, body)
                    if action == "artifacts" and self.command == "POST":
                        return self._send(200, {"items": o.artifacts(sid)})
                    if action == "context" and self.command == "GET":
                        collab.assert_can_read(sid, principal)
                        return self._send(200, {
                            "context": ctxs.get(sid)})
                    if action == "recovery" and self.command == "GET":
                        # §28.2 — forge/SessionRecoveryPlan/v1
                        collab.assert_can_read(sid, principal)
                        from .recovery import plan_for
                        sess: dict[str, Any] = {"id": sid}
                        for o2 in orchs.values():
                            for sx in o2.list_sessions():
                                if sx.id == sid:
                                    sess = sx.model_dump(mode="json")
                        prov = sess.get("provider") or provider
                        caps = {c.name: c.state for c in
                                _orch(str(prov)).adapter.detect().capabilities}
                        m = meta.get(sid)
                        n_ev = len(event_store.replay(sid))
                        return self._send(200, {"recovery": plan_for(
                            sess,
                            provider_resumable=str(
                                caps.get("session-resume", "")) == "supported",
                            events_count=n_ev,
                            context_version=m.get("context_version"))})
                except Exception as e:  # noqa: BLE001 — adapter errors vary; map to typed envelope
                    code = getattr(e, "code", "FAB-ERROR")
                    status = (403 if "FORBIDDEN" in code
                              else 429 if "BUDGET" in code
                              else 404 if "NOT-FOUND" in code
                              else 502)
                    return self._send(status, {"error": {"code": code,
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

        def _handoff(self, sid: str, provider: str, o: Any,
                     principal: str, body: dict[str, Any]) -> None:
            """§23.3 — session handoff. Modes:
            provider-resume   — real native resume via provider_session_ref
            context-rebuild   — new session + last events as context
                                (labeled 'reconstructed', never identical)
            remote            — requires a verified remote runner."""
            mode = str(body.get("mode", "context-rebuild"))
            audit.emit("session.handoff", principal, session=sid, mode=mode)
            if mode == "remote":
                try:
                    runners.place(str(body.get("runner_id", "")))
                except Exception as e:  # noqa: BLE001
                    return self._send(422, {"error": {
                        "code": getattr(e, "code", "FAB-UNAVAILABLE"),
                        "message": str(e)}})
                return self._send(200, {"handoff": "remote",
                                        "state": "accepted"})
            if mode == "provider-resume":
                s = o.sessions.get(sid)
                ref = s.provider_session_ref if s else None
                if not ref:
                    return self._send(422, {"error": {
                        "code": "FAB-UNSUPPORTED",
                        "message": "provider reports no resumable ref"}})
                ns = o.resume(ref)
                meta.upsert(ns.id, provider=provider)
                return self._send(201, {"handoff": "provider-resume",
                                        "session": ns.model_dump(mode="json")})
            # context-rebuild: honest reconstruction — new session seeded
            # with the last N events as context; labeled, never identical.
            history = [
                e for e in o.replay(sid)
                if e["type"] in ("message.completed", "turn.started")
            ][-20:]
            ns = o.create_session(
                product_id=meta.get(sid).get("product_id"),
                workspace_id=meta.get(sid).get("workspace_id"))
            meta.upsert(ns.id, provider=provider,
                        title=f"[rebuilt] {meta.get(sid).get('title', sid)}")
            context = "\n".join(
                f"{e['type']}: {e['payload'].get('text', '')[:400]}"
                for e in history)
            if context:
                o.prompt(ns.id, f"[context-rebuild from {sid}]\n{context}")
                o.drain(ns.id)
            return self._send(201, {"handoff": "context-rebuild",
                                    "continuity": "reconstructed",
                                    "session": ns.model_dump(mode="json"),
                                    "events_replayed": len(history)})

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
