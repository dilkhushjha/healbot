"""
stream.py — Server-Sent Events for live run streaming.
GET /stream/{run_id}       live logs + metrics per script run
GET /stream/batch/{id}     batch-level progress counter
"""
from core.database import engine, batches, script_runs
from core.live_frames import get_latest_frame
from core import run_context
from sqlalchemy import select
from fastapi.responses import StreamingResponse
from fastapi import APIRouter, HTTPException
import time
import json
import sys
import os

# ── sys.path fix ──────────────────────────────────────────────────────────────
_BACKEND_DIR = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
# ─────────────────────────────────────────────────────────────────────────────


router = APIRouter(prefix="/stream", tags=["Stream"])


@router.get("/{run_id}")
def stream_run(run_id: str):
    ctx = run_context.get(run_id)

    if not ctx:
        with engine.connect() as conn:
            row = conn.execute(
                select(script_runs).where(script_runs.c.id == run_id)
            ).mappings().first()
        if not row:
            raise HTTPException(404, f"Run {run_id} not found")

        def _done():
            latest = get_latest_frame(run_id)
            if latest:
                yield f"data: {json.dumps({'type':'snapshot','payload':{'metrics':{'llmCalls':row['llm_calls'],'visionCalls':row['vision_calls'],'healedSelectors':row['healed_steps'],'failures':row['failed_steps']},'status':row['status'],'run_id':run_id,'script_name':row['script_name'],'log_count':0,**latest}})}\n\n"
            yield f"data: {json.dumps({'type':'done','payload':{'status':row['status'],'run_id':run_id}})}\n\n"
        return StreamingResponse(_done(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def _live():
        sent = 0
        while True:
            for entry in ctx.get_logs(since=sent):
                yield f"data: {json.dumps({'type':'log','payload':entry})}\n\n"
                sent += 1
            yield f"data: {json.dumps({'type':'snapshot','payload':ctx.get_snapshot()})}\n\n"
            if ctx.get_status() in ("passed", "failed", "healed", "error"):
                yield f"data: {json.dumps({'type':'done','payload':{'status':ctx.get_status(),'run_id':run_id}})}\n\n"
                break
            time.sleep(0.4)

    return StreamingResponse(_live(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/batch/{batch_id}")
def stream_batch(batch_id: str):
    def _batch():
        while True:
            with engine.connect() as conn:
                row = conn.execute(
                    select(batches).where(batches.c.id == batch_id)
                ).mappings().first()
            if not row:
                yield f"data: {json.dumps({'type':'error','message':'batch not found'})}\n\n"
                break
            yield f"data: {json.dumps({'type':'progress','payload':{'batch_id':batch_id,'status':row['status'],'total':row['total_scripts'],'completed':row['completed'],'passed':row['passed'],'healed':row['healed'],'failed':row['failed']}})}\n\n"
            if row["status"] in ("completed", "failed", "cancelled"):
                yield f"data: {json.dumps({'type':'done','payload':{'status':row['status']}})}\n\n"
                break
            time.sleep(1)

    return StreamingResponse(_batch(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
