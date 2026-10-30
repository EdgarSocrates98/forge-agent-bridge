"""Part IX — deterministic strategic capabilities over bridge state.

No LLM, no wall-clock inside scorers: every verdict derives from recorded
events, capability matrices, budgets, and context bindings — with explicit
reason codes, never arbitrary heuristics.

  route_provider      §13.4  routing scored on declared constraints
  evaluate_session    §13.5  session quality from recorded events
  context_health      §13.7  bound-context health report
  finops_report       §13.8  cost rollup by scope, real vs estimated
  replay_detail       §13.9  read-only replay dossier (no re-execution)
  degraded_mode       §13.10 honest capability state when providers are out
  workspace_summary   §13.1  federated inventory view
  decision_records    §13.6  sessions → forge/ProductDecisionRecord/v1
"""

from __future__ import annotations

from typing import Any

DECISION_SCHEMA = "forge/ProductDecisionRecord/v1"


# ---- 13.4 Provider Routing Intelligence ---------------------------------

def route_provider(providers: list[dict[str, Any]], *,
                   task_type: str = "chat",
                   required: list[str] | None = None,
                   privacy: str = "local-ok",
                   prefer: str | None = None,
                   max_cost_usd: float | None = None) -> dict[str, Any]:
    """Score providers on declared constraints — every point has a reason."""
    required = required or [task_type]
    scored: list[dict[str, Any]] = []
    for p in providers:
        caps = {c["name"]: c["state"] for c in p.get("capabilities", [])}
        reasons: list[str] = []
        score = 0.0
        hard_fail = False
        for cap in required:
            st = caps.get(cap, "unsupported")
            if st == "supported":
                score += 2; reasons.append(f"{cap}:supported +2")
            elif st in ("unverified", "experimental", "requires-authentication",
                        "requires-configuration"):
                score += 0.5; reasons.append(f"{cap}:{st} +0.5")
            else:
                hard_fail = True
                reasons.append(f"{cap}:{st} (disqualified)")
        if not p.get("executable") and p.get("kind") != "fake":
            hard_fail = True; reasons.append("executable:missing (disqualified)")
        if privacy == "local-only" and caps.get("cloud-handoff") == "supported":
            score -= 1; reasons.append("cloud-handoff present, local-only −1")
        if prefer and p["id"] == prefer:
            score += 1; reasons.append("user-preference +1")
        if p.get("auth_state") == "authenticated":
            score += 1; reasons.append("authenticated +1")
        scored.append({"provider": p["id"], "score": round(score, 2),
                       "eligible": not hard_fail, "reasons": reasons,
                       "auth_state": p.get("auth_state")})
    scored.sort(key=lambda s: (-s["eligible"], -s["score"]))
    return {"schema": "forge/ProviderRouting/v1",
            "task_type": task_type, "required": required,
            "candidates": scored,
            "selected": scored[0]["provider"]
            if scored and scored[0]["eligible"] else None,
            "note": "deterministic scoring — no hidden heuristics"}


# ---- 13.5 Session Quality Evaluator --------------------------------------

def evaluate_session(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic quality axes from the recorded event stream."""
    axes: dict[str, Any] = {}
    turns = [e for e in events if e["type"] == "turn.started"]
    done = [e for e in events if e["type"] == "turn.completed"]
    failed = [e for e in events if e["type"] in ("turn.failed", "runtime.error")]
    tools = [e for e in events if e["type"].startswith("tool.")]
    tool_fails = [e for e in tools
                  if e["payload"].get("status") in ("failed", "error")]
    approvals = [e for e in events if e["type"] == "approval.requested"]
    msgs = [e for e in events if e["type"].startswith("message.")]
    grounded = [e for e in msgs if e["payload"].get("citations")]
    usage = [e for e in events if e["type"] == "usage.updated"]

    def _n(v: Any) -> int:
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0  # redacted/non-numeric payloads stay 0

    tin = sum(_n(e["payload"].get("tokens_in")) for e in usage)
    tout = sum(_n(e["payload"].get("tokens_out")) for e in usage)

    axes["task_completion"] = {
        "score": (len(done) / len(turns)) if turns else 0.0,
        "turns": len(turns), "completed": len(done), "failed": len(failed)}
    axes["tool_correctness"] = {
        "score": (1 - len(tool_fails) / len(tools)) if tools else 1.0,
        "calls": len(tools), "failed": len(tool_fails)}
    axes["groundedness"] = {
        "score": (len(grounded) / len(msgs)) if msgs else 0.0,
        "messages": len(msgs), "with_citations": len(grounded)}
    axes["policy_compliance"] = {
        "score": 1.0 - min(1.0, len(failed) / max(1, len(events))),
        "violations": len(failed), "approvals": len(approvals)}
    axes["cost_efficiency"] = {
        "tokens_in": tin, "tokens_out": tout,
        "measured": bool(usage),
        "note": "estimated" if not usage else "provider-reported"}
    axes["latency"] = {"note": "per-event timestamps preserved; "
                               "wall-clock scoring is a client concern"}
    overall = round(sum(
        axes[k]["score"] for k in
        ("task_completion", "tool_correctness",
         "groundedness", "policy_compliance")) / 4, 3)
    return {"schema": "forge/SessionQuality/v1", "axes": axes,
            "overall": overall,
            "note": "deterministic — no LLM judgment"}


# ---- 13.7 Context Health --------------------------------------------------

def context_health(ctx: dict[str, Any] | None) -> dict[str, Any]:
    """Health of a bound ProductAgentSessionContext — freshness vs expiry,
    allowlist coverage, empty-bindings flagged."""
    if not ctx:
        return {"schema": "forge/ContextHealth/v1", "state": "unbound",
                "score": 0.0, "findings": ["no context bound to session"]}
    findings: list[str] = []
    checks = {
        "has_product": bool(ctx.get("product_id")),
        "has_allowlists": bool(ctx.get("allowed_tools")
                               or ctx.get("allowed_knowledge_sources")),
        "not_expired": not (ctx.get("expires_at")
                            and ctx["expires_at"] < 1e10),
        "versioned": bool(ctx.get("context_version")),
    }
    for k, ok in checks.items():
        if not ok:
            findings.append(k.replace("_", "-"))
    score = round(sum(checks.values()) / len(checks), 3)
    return {"schema": "forge/ContextHealth/v1",
            "state": "healthy" if score == 1.0 else "degraded",
            "score": score, "checks": checks, "findings": findings,
            "context_version": ctx.get("context_version")}


# ---- 13.8 Agent FinOps -----------------------------------------------------

def finops_report(ledger: dict[str, Any]) -> dict[str, Any]:
    """Cost rollup over the BudgetLedger — keys scope:key:window:wkey."""
    usage = (ledger or {}).get("usage", {})
    limits = (ledger or {}).get("limits", {})
    by_scope: dict[str, dict[str, Any]] = {}
    for k, u in usage.items():
        scope, _, key, window, wkey = k.split(":", 4) if k.count(":") >= 4 \
            else (*k.split(":"), "", "")[:5]
        slot = by_scope.setdefault(
            f"{scope}:{key}",
            {"scope": scope, "value": key,
             "tokens_in": 0, "tokens_out": 0,
             "estimated": False, "windows": {}})
        slot["tokens_in"] += int(u.get("in") or 0)
        slot["tokens_out"] += int(u.get("out") or 0)
        slot["estimated"] = slot["estimated"] or bool(u.get("estimated"))
        slot["windows"][f"{window}:{wkey}"] = {
            "in": u.get("in"), "out": u.get("out")}
    return {"schema": "forge/AgentFinOps/v1",
            "by_scope": sorted(by_scope.values(),
                               key=lambda s: -(s["tokens_in"]
                                               + s["tokens_out"])),
            "limits": limits,
            "note": "token counts real; USD cost only when provider-reported"}


# ---- 13.9 Replay & Debug Studio (read-only) --------------------------------

def replay_detail(events: list[dict[str, Any]],
                  context: dict[str, Any] | None) -> dict[str, Any]:
    """Investigation dossier — inputs, tools, approvals, errors, context
    version. Read-only: replays never re-execute actions (§13.9)."""
    return {"schema": "forge/ReplayDossier/v1",
            "inputs": [e for e in events if e["type"] == "turn.started"],
            "tools": [e for e in events if e["type"].startswith("tool.")],
            "approvals": [e for e in events
                          if e["type"].startswith("approval.")],
            "errors": [e for e in events
                       if e["type"] in ("turn.failed", "runtime.error")],
            "context_version": (context or {}).get("context_version"),
            "event_count": len(events),
            "replay_mode": "read-only",
            "note": "re-execution requires sandbox + explicit consent — "
                    "not available via this endpoint"}


# ---- 13.10 Offline/Degraded Mode -------------------------------------------

def degraded_mode(providers: list[dict[str, Any]]) -> dict[str, Any]:
    """Honest capability surface when providers are unavailable."""
    avail = [p["id"] for p in providers
             if p.get("executable") or p.get("kind") == "fake"]
    degraded = len(avail) == 0 or all(
        p.get("auth_state") != "authenticated" for p in providers
        if p["id"] in avail)
    return {"schema": "forge/DegradedMode/v1",
            "degraded": degraded,
            "available_providers": avail,
            "allowed_operations": [
                "session history read (authorized sessions only)",
                "local artifact view", "cached knowledge navigation",
                "diagnostics", "draft composition"],
            "forbidden_operations": [
                "auto-resubmit of queued prompts without re-authorization",
                "side-effecting actions on stale sessions"],
            "note": "queued prompts are never auto-executed after reconnect"}


# ---- 13.1 Forge Workspace Intelligence -------------------------------------

def workspace_summary(sessions: dict[str, Any],
                      contexts: dict[str, Any],
                      mcp_servers: list[dict[str, Any]],
                      budgets: dict[str, Any]) -> dict[str, Any]:
    """Federated inventory: sessions + contexts + MCP + budgets, linked."""
    products: dict[str, list[str]] = {}
    for sid, m in sessions.items():
        pid = m.get("product_id") or "unbound"
        products.setdefault(pid, []).append(sid)
    return {"schema": "forge/WorkspaceIntelligence/v1",
            "products": {p: {"sessions": sids, "session_count": len(sids)}
                         for p, sids in products.items()},
            "sessions_total": len(sessions),
            "contexts_bound": len(contexts),
            "mcp_servers": [{"id": m["server_id"], "trust": m["trust"],
                             "health": m["health"]} for m in mcp_servers],
            "budget_scopes": len(budgets or {}),
            "search_hint": "filter by product_id → sessions → events"}


# ---- 13.6 Product Decision Intelligence ------------------------------------

def decision_records(events: list[dict[str, Any]],
                     session_id: str, product_id: str) -> list[dict[str, Any]]:
    """Extract decision candidates from approvals + completed turns.
    Produces forge/ProductDecisionRecord/v1 drafts — a human approves the
    record; automation never declares a product decision."""
    out: list[dict[str, Any]] = []
    for e in events:
        if e["type"] == "approval.resolved" and e["payload"].get("approved"):
            out.append({
                "schema": DECISION_SCHEMA,
                "session_id": session_id, "product_id": product_id,
                "what": str(e["payload"].get("detail") or "approval resolved"),
                "why": str(e["payload"].get("reason") or ""),
                "evidence_event_id": e["id"],
                "assumptions": [], "owner": "",
                "decided_at": e["ts"], "expected_impact": "",
                "validation_plan": [],
                "state": "draft-needs-owner-review"})
    return out
