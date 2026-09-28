"""
batches.py router — Submit and query script batches.
POST /batches              Submit a batch of journeys
GET  /batches              List all batches for tenant
GET  /batches/{id}         Batch detail + script run summaries
GET  /batches/{id}/runs    Script runs within a batch
GET  /batches/{id}/report  Full analytics report for a batch
"""
from journey_runner import run_journey
from journey_schema import validate, normalise
from core.config import TIER_LIMITS
from core.batch_scheduler import submit_batch, queue_depth
from core.database import engine, batches, environments, projects, script_runs, heal_events, now
from core.runner_capabilities import default_capability, execution_status, resolve_capability
from api.permissions import TEST_RUNNER_ROLES, require_role
from sqlalchemy import select, update
from fastapi import APIRouter, HTTPException, Request
from datetime import datetime, timedelta
import sys
import os

# ── sys.path fix ──────────────────────────────────────────────────────────────
_BACKEND_DIR = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
# ─────────────────────────────────────────────────────────────────────────────


router = APIRouter(prefix="/batches", tags=["Batches"])
STALE_SDK_RUN_SECONDS = 120


def _expire_stale_sdk_batches(tenant_id: str):
    from api.routers.sessions import active_batch_ids

    active = active_batch_ids()
    cutoff = now() - timedelta(seconds=STALE_SDK_RUN_SECONDS)
    with engine.begin() as conn:
        rows = conn.execute(
            select(batches).where(
                batches.c.tenant_id == tenant_id,
                batches.c.status == "running",
                batches.c.submitted_by.like("sdk:%"),
            )
        ).mappings().all()

        for row in rows:
            if row["id"] in active:
                continue
            started_at = row["started_at"] or row["created_at"]
            if not started_at:
                continue
            if isinstance(started_at, str):
                try:
                    started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                except ValueError:
                    started_at = cutoff
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=cutoff.tzinfo)
            if started_at > cutoff:
                continue

            conn.execute(update(script_runs).where(
                script_runs.c.batch_id == row["id"],
                script_runs.c.tenant_id == tenant_id,
                script_runs.c.status == "running",
            ).values(
                status="error",
                error="SDK run ended without a final session event",
                failed_steps=1,
                finished_at=now(),
            ))
            conn.execute(update(batches).where(
                batches.c.id == row["id"],
                batches.c.tenant_id == tenant_id,
            ).values(
                status="failed",
                completed=1,
                failed=1,
                finished_at=now(),
            ))


def _resolve_target(tenant_id: str, project_id: str | None, environment_id: str | None) -> tuple[str | None, str | None, dict]:
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
                raise HTTPException(404, "Environment not found")
            if project_id and environment["project_id"] != project_id:
                raise HTTPException(422, "Environment does not belong to the supplied project")
            project_id = environment["project_id"]
            capability = resolve_capability(
                conn, tenant_id, environment["runner_capability_id"]
            ) if environment["runner_capability_id"] else default_capability()
            if environment["runner_capability_id"] and not capability:
                raise HTTPException(422, "Environment references a missing runner capability")

        if project_id:
            project = conn.execute(
                select(projects).where(
                    projects.c.id == project_id,
                    projects.c.tenant_id == tenant_id,
                )
            ).mappings().first()
            if not project:
                raise HTTPException(404, "Project not found")

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
    return project_id, environment_id, snapshot


@router.post("")
def submit(payload: dict, request: Request):
    require_role(request, TEST_RUNNER_ROLES)
    tenant = request.state.tenant
    name = payload.get("name", "Unnamed batch")
    project_id = payload.get("project_id")
    environment_id = payload.get("environment_id")
    scripts = payload.get("scripts", [])

    if not scripts:
        raise HTTPException(422, "Batch must contain at least one script")

    project_id, environment_id, environment_snapshot = _resolve_target(
        tenant["id"], project_id, environment_id
    )
    runnable, reason = execution_status(environment_snapshot.get("runner_capability"))
    if not runnable:
        raise HTTPException(422, reason)

    normalised = []
    for i, s in enumerate(scripts):
        candidate = s
        if environment_snapshot.get("base_url") and isinstance(candidate, dict) and not candidate.get("base_url"):
            candidate = {**candidate, "base_url": environment_snapshot["base_url"]}
        ok, err = validate(candidate)
        if not ok:
            script_name = candidate.get("name", "?") if isinstance(candidate, dict) else "?"
            raise HTTPException(
                422, f"Script {i+1} ({script_name}): {err}")
        item = normalise(candidate)
        if environment_snapshot:
            item["environment"] = environment_snapshot
        normalised.append(item)

    try:
        batch_id = submit_batch(
            tenant=tenant, project_id=project_id, batch_name=name,
            script_list=normalised, runner_fn=run_journey, submitted_by="api",
            environment_id=environment_id,
            environment_snapshot=environment_snapshot,
        )
    except PermissionError as e:
        raise HTTPException(429, str(e))
    except Exception as e:
        raise HTTPException(500, f"Failed to queue batch: {e}")

    tier = tenant.get("tier", "free")
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
    return {
        "batch_id":    batch_id,
        "status":      "queued",
        "scripts":     len(normalised),
        "queue_depth": queue_depth(),
        "tier":        tier,
        "daily_limit": limits["scripts_per_day"],
        "project_id": project_id,
        "environment_id": environment_id,
        "environment": environment_snapshot,
    }


@router.get("")
def list_batches(request: Request, limit: int = 50):
    tenant = request.state.tenant
    _expire_stale_sdk_batches(tenant["id"])
    with engine.connect() as conn:
        rows = conn.execute(
            select(batches).where(batches.c.tenant_id == tenant["id"])
            .order_by(batches.c.created_at.desc()).limit(limit)
        ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{batch_id}")
def get_batch(batch_id: str, request: Request):
    tenant = request.state.tenant
    _expire_stale_sdk_batches(tenant["id"])
    with engine.connect() as conn:
        batch = conn.execute(
            select(batches).where(
                batches.c.id == batch_id,
                batches.c.tenant_id == tenant["id"]
            )
        ).mappings().first()
        if not batch:
            raise HTTPException(404, "Batch not found")
        runs = conn.execute(
            select(script_runs).where(script_runs.c.batch_id == batch_id)
            .order_by(script_runs.c.script_index)
        ).mappings().all()
    return {**dict(batch), "runs": [dict(r) for r in runs]}


@router.get("/{batch_id}/runs")
def get_runs(batch_id: str, request: Request):
    tenant = request.state.tenant
    _expire_stale_sdk_batches(tenant["id"])
    with engine.connect() as conn:
        rows = conn.execute(
            select(script_runs).where(
                script_runs.c.batch_id == batch_id,
                script_runs.c.tenant_id == tenant["id"]
            ).order_by(script_runs.c.script_index)
        ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{batch_id}/report")
def batch_report(batch_id: str, request: Request):
    tenant = request.state.tenant
    with engine.connect() as conn:
        batch = conn.execute(
            select(batches).where(
                batches.c.id == batch_id,
                batches.c.tenant_id == tenant["id"]
            )
        ).mappings().first()
        if not batch:
            raise HTTPException(404, "Batch not found")
        runs = conn.execute(
            select(script_runs).where(script_runs.c.batch_id == batch_id)
            .order_by(script_runs.c.script_index)
        ).mappings().all()
        heals = conn.execute(
            select(heal_events).where(
                heal_events.c.run_id.in_([r["id"] for r in runs])
            )
        ).mappings().all()

    strategies = {}
    for h in heals:
        s = h["strategy"] or "unknown"
        strategies[s] = strategies.get(s, 0) + 1

    total = len(runs)
    passed = sum(1 for r in runs if r["status"] in ("passed", "healed"))
    failed = sum(1 for r in runs if r["status"] == "failed")
    heal_rt = round((batch["healed"] / total * 100) if total else 0, 1)

    return {
        "batch_id":           batch_id,
        "batch_name":         batch["name"],
        "status":             batch["status"],
        "total_scripts":      total,
        "passed":             passed,
        "healed":             batch["healed"],
        "failed":             failed,
        "heal_rate_pct":      heal_rt,
        "strategy_breakdown": strategies,
        "script_summaries": [
            {
                "script_name":  r["script_name"],
                "status":       r["status"],
                "duration_ms":  r["duration_ms"],
                "healed_steps": r["healed_steps"],
                "failed_steps": r["failed_steps"],
                "llm_calls":    r["llm_calls"],
            }
            for r in runs
        ],
        "duration_s": round(
            (batch["finished_at"] - batch["started_at"]).total_seconds(), 1
        ) if batch["finished_at"] and batch["started_at"] else None,
    }
