"""
heal.py — Inline selector healing endpoint.
Called by healbot-sdk on every NoSuchElementException.
"""
from healing.healing_engine import heal_selector
from healing.llm_providers import provider_descriptor
from core.logger import log as _log
from core.database import engine, batches, heal_events, upsert_step, now
from api.permissions import TEST_RUNNER_ROLES, require_role
from sqlalchemy import update
from pydantic import BaseModel
from fastapi import APIRouter, Request
import hashlib
import sys
import os

# ── sys.path fix ──────────────────────────────────────────────────────────────
_BACKEND_DIR = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
# ─────────────────────────────────────────────────────────────────────────────


router = APIRouter(prefix="/heal", tags=["Heal"])


class HealRequest(BaseModel):
    selector:   str
    html:       str
    intent:     str = ""
    test_name:  str = ""
    session_id: str = ""


class HealResponse(BaseModel):
    healed:    str | None
    strategy:  str | None
    dom_score: int
    llm_used:  bool
    llm_provider: str | None = None
    llm_model: str | None = None
    success:   bool


@router.post("", response_model=HealResponse)
def heal(req: HealRequest, request: Request):
    require_role(request, TEST_RUNNER_ROLES)
    tenant = request.state.tenant
    tenant_id = tenant["id"]

    # Look up session
    sess = ctx = None
    if req.session_id:
        from api.routers.sessions import get_session
        sess = get_session(req.session_id)
        if sess:
            ctx = sess["ctx"]

    step_id = hashlib.md5(
        f"{req.test_name}:{req.selector}".encode()).hexdigest()[:8]
    _log("ENGINE",
         f"Healing [{req.test_name or 'unknown'}]: {req.selector[:60]}", ctx=ctx)

    if sess:
        upsert_step(sess["run_id"], step_id, tenant_id,
                    description=req.test_name or req.selector[:40],
                    action="find_element",
                    original_selector=req.selector,
                    status="running", started_at=now())

    result = heal_selector(
        old_selector=req.selector,
        new_html=req.html,
        intent=req.intent or None,
        tenant_id=tenant_id,
        run_id=sess["run_id"] if sess else (req.session_id or "inline"),
        step_id=step_id,
        ctx=ctx,
    )
    success = result["healed"] is not None
    llm_descriptor = provider_descriptor() if result["llm_invoked"] else {}

    if sess:
        run_id = sess["run_id"]
        batch_id = sess["batch_id"]

        with engine.begin() as conn:
            conn.execute(heal_events.insert().values(
                run_id=run_id,
                tenant_id=tenant_id,
                step_id=step_id,
                selector=req.selector,
                intent=req.intent or "",
                dom_score=result["dom_score"],
                dom_candidate=result["dom_candidate"],
                llm_invoked=result["llm_invoked"],
                llm_candidate=result["llm_candidate"],
                final_selector=result["healed"],
                strategy=result["strategy"],
                success=success,
                created_at=now(),
            ))

        step_status = "healed" if success else "fail"
        upsert_step(run_id, step_id, tenant_id,
                    status=step_status,
                    healed_selector=result["healed"],
                    strategy=result["strategy"],
                    finished_at=now())

        ctx.push({
            "type":              "step",
            "step_id":           step_id,
            "status":            step_status,
            "description":       req.test_name or req.selector[:50],
            "original_selector": req.selector,
            "healed_selector":   result["healed"],
            "strategy":          result["strategy"],
            "llm_used":          result["llm_invoked"],
            "reason":            "" if success else "All strategies exhausted",
            "vision_verdict":    result.get("vision_verdict", "unknown"),
            "vision_note":       result.get("vision_note", ""),
            "critical":          False,
        })

        if success:
            sess["healed"] += 1
            ctx.increment("healedSelectors")
        else:
            sess["failed"] += 1
            ctx.increment("failures")

        with engine.begin() as conn:
            conn.execute(update(batches).where(batches.c.id == batch_id).values(
                healed=sess["healed"], failed=sess["failed"]
            ))

    return HealResponse(
        healed=result["healed"],
        strategy=result["strategy"],
        dom_score=result["dom_score"],
        llm_used=result["llm_invoked"],
        llm_provider=llm_descriptor.get("provider"),
        llm_model=llm_descriptor.get("model"),
        success=success,
    )
