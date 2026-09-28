"""
sessions.py — SDK session lifecycle.
POST /sessions/start  → creates batch + script_run + RunContext → dashboard shows it
POST /sessions/end    → finalises batch + script_run
GET  /sessions        → list SDK sessions
"""
from core.logger import log as _log
from core.run_context import RunContext, register
from core.live_frames import save_latest_frame
from core.database import engine, batches, environments, projects, script_runs, now, increment_usage, upsert_step
from core.runner_capabilities import default_capability, resolve_capability
from api.permissions import TEST_RUNNER_ROLES, require_role
from sqlalchemy import update, select
from pydantic import BaseModel
from fastapi import APIRouter, Request
from datetime import datetime, timezone
import uuid
import sys
import os

# ── sys.path fix — MUST be before local imports ───────────────────────────────
_BACKEND_DIR = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
# ─────────────────────────────────────────────────────────────────────────────


router = APIRouter(prefix="/sessions", tags=["Sessions"])

_sessions: dict = {}   # session_id → { run_id, batch_id, ctx, healed, failed, last_seen_at }
STALE_SESSION_SECONDS = 120


class StartRequest(BaseModel):
    name:      str = ""
    framework: str = "unknown"
    project_id: str = ""
    environment_id: str = ""


class EndRequest(BaseModel):
    session_id: str


class EventRequest(BaseModel):
    session_id: str
    event_type: str = "step"
    status: str = "running"
    description: str = ""
    selector: str = ""
    healed_selector: str = ""
    strategy: str = ""
    llm_used: bool = False
    screenshot: str = ""
    message: str = ""


def _resolve_target(tenant_id: str, project_id: str, environment_id: str) -> tuple[str | None, str | None, dict]:
    project_id = project_id or ""
    environment_id = environment_id or ""
    if not project_id and not environment_id:
        return None, None, {}

    with engine.connect() as conn:
        project = None
        environment = None
        capability = None
        if environment_id:
            environment = conn.execute(
                select(environments).where(
                    environments.c.id == environment_id,
                    environments.c.tenant_id == tenant_id,
                    environments.c.is_active == True,
                )
            ).mappings().first()
            if not environment:
                environment_id = ""
            if environment and project_id and environment["project_id"] != project_id:
                environment = None
                environment_id = ""
            if environment:
                project_id = environment["project_id"]
                capability = resolve_capability(
                    conn, tenant_id, environment["runner_capability_id"]
                ) if environment["runner_capability_id"] else default_capability()

        if project_id:
            project = conn.execute(
                select(projects).where(
                    projects.c.id == project_id,
                    projects.c.tenant_id == tenant_id,
                )
            ).mappings().first()
            if not project:
                return None, None, {}

    snapshot = {}
    if environment:
        snapshot = {
            "id": environment["id"],
            "project_id": environment["project_id"],
            "project_name": project["name"] if project else "",
            "name": environment["name"],
            "base_url": environment["base_url"] or "",
            "framework": environment["framework"],
            "browser": environment["browser"],
            "platform": environment["platform"],
            "runner_capability_id": environment["runner_capability_id"],
            "runner_capability": capability,
            "variables": environment["variables"] or {},
        }
    elif project:
        snapshot = {
            "project_id": project["id"],
            "project_name": project["name"],
        }
    return project_id or None, environment_id or None, snapshot


@router.post("/start")
def start_session(req: StartRequest, request: Request):
    require_role(request, TEST_RUNNER_ROLES)
    tenant = request.state.tenant
    tenant_id = tenant["id"]

    session_id = str(uuid.uuid4())[:8]
    batch_id = str(uuid.uuid4())[:8]
    run_id = str(uuid.uuid4())[:8]
    project_id, environment_id, environment_snapshot = _resolve_target(
        tenant_id, req.project_id, req.environment_id
    )
    name = req.name or f"SDK Session — {datetime.now().strftime('%H:%M:%S')}"

    with engine.begin() as conn:
        conn.execute(batches.insert().values(
            id=batch_id,
            tenant_id=tenant_id,
            project_id=project_id,
            environment_id=environment_id,
            environment_snapshot=environment_snapshot,
            name=name,
            status="running",
            total_scripts=1,
            completed=0,
            passed=0,
            healed=0,
            failed=0,
            created_at=now(),
            started_at=now(),
            submitted_by=f"sdk:{req.framework}",
        ))
        conn.execute(script_runs.insert().values(
            id=run_id,
            batch_id=batch_id,
            tenant_id=tenant_id,
            script_name=name,
            script_index=0,
            status="running",
            total_steps=0,
            created_at=now(),
            started_at=now(),
        ))

    ctx = RunContext(run_id, name)
    ctx.set_status("running")
    register(ctx)

    _log(
        "SESSION", f"Started [{session_id}] batch={batch_id} run={run_id}", ctx=ctx)

    _sessions[session_id] = {
        "run_id":    run_id,
        "batch_id":  batch_id,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "environment_id": environment_id,
        "environment": environment_snapshot,
        "ctx":       ctx,
        "name":      name,
        "healed":    0,
        "failed":    0,
        "last_seen_at": datetime.now(timezone.utc),
    }

    return {
        "session_id": session_id,
        "run_id":     run_id,
        "batch_id":   batch_id,
        "stream_url": f"/stream/{run_id}",
        "status":     "running",
        "project_id": project_id,
        "environment_id": environment_id,
        "environment": environment_snapshot,
    }


@router.post("/end")
def end_session(req: EndRequest, request: Request):
    require_role(request, TEST_RUNNER_ROLES)
    tenant = request.state.tenant
    sess = _sessions.get(req.session_id)
    if not sess:
        return {"error": "session not found or already ended"}

    run_id = sess["run_id"]
    batch_id = sess["batch_id"]
    ctx = sess["ctx"]
    healed = sess["healed"]
    failed_c = sess["failed"]
    total = healed + failed_c
    heal_rt = round(healed / total * 100, 1) if total else 0
    metrics = ctx.get_metrics()

    final_status = "healed" if healed > 0 else (
        "passed" if failed_c == 0 else "failed")

    with engine.begin() as conn:
        conn.execute(update(script_runs).where(script_runs.c.id == run_id).values(
            status=final_status,
            healed_steps=healed,
            failed_steps=failed_c,
            llm_calls=metrics.get("llmCalls", 0),
            vision_calls=metrics.get("visionCalls", 0),
            finished_at=now(),
        ))
        conn.execute(update(batches).where(batches.c.id == batch_id).values(
            status="completed",
            completed=1,
            passed=1 if final_status in ("passed", "healed") else 0,
            healed=1 if final_status == "healed" else 0,
            failed=1 if final_status == "failed" else 0,
            finished_at=now(),
        ))

    increment_usage(tenant["id"], datetime.now().strftime(
        "%Y-%m-%d"), scripts=1, heals=healed)
    ctx.set_status(final_status)
    _log("SESSION",
         f"Ended [{req.session_id}] healed={healed} failed={failed_c}", ctx=ctx)
    del _sessions[req.session_id]

    return {
        "session_id": req.session_id,
        "run_id":     run_id,
        "batch_id":   batch_id,
        "healed":     healed,
        "failed":     failed_c,
        "heal_rate":  heal_rt,
        "status":     final_status,
    }


@router.post("/event")
def record_session_event(req: EventRequest, request: Request):
    require_role(request, TEST_RUNNER_ROLES)
    expire_stale_sessions()
    sess = _sessions.get(req.session_id)
    if not sess:
        return {"ok": False, "reason": "session not found or already ended"}

    run_id = sess["run_id"]
    tenant_id = sess["tenant_id"]
    ctx = sess["ctx"]
    sess["last_seen_at"] = datetime.now(timezone.utc)

    if req.event_type == "heartbeat":
        ctx.push({
            "type": "heartbeat",
            "status": "running",
            "message": req.message or "SDK heartbeat",
        })
        return {"ok": True, "run_id": run_id}
    source = req.selector or req.description or req.message or req.event_type
    step_id = str(abs(hash(f"{req.event_type}:{source}")))[:10]

    payload = {
        "type": req.event_type,
        "step_id": step_id,
        "status": req.status,
        "description": req.description or req.message or source,
        "original_selector": req.selector,
        "healed_selector": req.healed_selector,
        "strategy": req.strategy,
        "llm_used": req.llm_used,
        "screenshot": req.screenshot,
        "message": req.message,
    }
    ctx.push(payload)
    if req.screenshot:
        save_latest_frame(run_id, req.screenshot, payload["time"])

    if req.event_type == "step":
        upsert_step(
            run_id,
            step_id,
            tenant_id,
            description=payload["description"],
            action="find_element",
            original_selector=req.selector,
            healed_selector=req.healed_selector or None,
            status=req.status,
            strategy=req.strategy or None,
            started_at=now(),
            finished_at=now() if req.status in {"pass", "passed", "healed", "fail", "failed"} else None,
        )

    return {"ok": True, "run_id": run_id}


def get_session(session_id: str) -> dict | None:
    expire_stale_sessions()
    return _sessions.get(session_id)


def active_batch_ids() -> set[str]:
    expire_stale_sessions()
    return {sess["batch_id"] for sess in _sessions.values()}


def expire_stale_sessions(max_idle_seconds: int = STALE_SESSION_SECONDS) -> list[str]:
    now_utc = datetime.now(timezone.utc)
    expired = []
    for session_id, sess in list(_sessions.items()):
        last_seen = sess.get("last_seen_at") or now_utc
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if (now_utc - last_seen).total_seconds() <= max_idle_seconds:
            continue

        run_id = sess["run_id"]
        batch_id = sess["batch_id"]
        ctx = sess["ctx"]
        ctx.push({
            "type": "system",
            "status": "error",
            "message": "SDK heartbeat lost. Marking execution as stale.",
        })
        ctx.set_status("error")
        with engine.begin() as conn:
            conn.execute(update(script_runs).where(script_runs.c.id == run_id).values(
                status="error",
                error="SDK heartbeat lost",
                failed_steps=max(sess.get("failed", 0), 1),
                finished_at=now(),
            ))
            conn.execute(update(batches).where(batches.c.id == batch_id).values(
                status="failed",
                completed=1,
                failed=1,
                finished_at=now(),
            ))
        del _sessions[session_id]
        expired.append(session_id)
    return expired


@router.get("")
def list_sessions(request: Request, limit: int = 20):
    tenant = request.state.tenant
    with engine.connect() as conn:
        rows = conn.execute(
            select(batches)
            .where(batches.c.tenant_id == tenant["id"],
                   batches.c.submitted_by.like("sdk:%"))
            .order_by(batches.c.created_at.desc())
            .limit(limit)
        ).mappings().all()
    return [dict(r) for r in rows]
