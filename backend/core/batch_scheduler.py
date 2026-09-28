"""
batch_scheduler.py — Batch execution engine.

A batch is a collection of scripts submitted together.
Scripts within a batch run sequentially (one after another) by default,
but multiple batches can run in parallel (one per worker thread).

Flow:
  submit_batch(tenant, scripts[]) → batch_id
       │
       ▼
  BatchWorker picks up batch from queue
       │
       for each script in batch:
         ├── create script_run record
         ├── run journey (via journey_runner)
         ├── update script_run record
         └── update batch counters
       │
  batch finished → analytics updated → alert sent (if configured)
"""

import queue
import threading
import uuid
import os
from datetime import datetime, timezone
from typing import Callable

from core.config import MAX_WORKERS, MAX_QUEUED, TIER_LIMITS
from core.database import (
    engine, batches, script_runs, now,
    increment_usage, get_daily_usage
)
from core.run_context import RunContext, register
from core.logger import log as _log
from sqlalchemy import update, select
import atexit

_batch_queue: queue.Queue = queue.Queue(maxsize=MAX_QUEUED)
_contexts:  dict = {}   # run_id → RunContext
_ctx_lock = threading.Lock()
_started = False
_start_lock = threading.Lock()


# ── Worker ─────────────────────────────────────────────────────────────────────

def _worker():
    while True:
        job = _batch_queue.get()
        if job is None:
            _batch_queue.task_done()
            break
        batch_id, tenant, script_list, runner_fn = job
        try:
            _execute_batch(batch_id, tenant, script_list, runner_fn)
        except Exception as e:
            _log("BATCH", f"Batch {batch_id} crashed: {e}", level="error")
            with engine.begin() as conn:
                conn.execute(update(batches).where(batches.c.id == batch_id).values(
                    status="failed", finished_at=now()
                ))
        finally:
            _batch_queue.task_done()


def _execute_batch(batch_id: str, tenant: dict, script_list: list, runner_fn: Callable):
    tenant_id = tenant["id"]
    date_str = datetime.now().strftime("%Y-%m-%d")

    _log(
        "BATCH", f"[{batch_id}] Starting — {len(script_list)} scripts — tenant={tenant_id}")

    with engine.begin() as conn:
        conn.execute(update(batches).where(batches.c.id == batch_id).values(
            status="running", started_at=now()
        ))

    batch_passed = batch_healed = batch_failed = 0

    for idx, script_def in enumerate(script_list):
        run_id = str(uuid.uuid4())[:8]
        script_name = script_def.get("name", f"script_{idx+1}")

        # Create run record
        with engine.begin() as conn:
            conn.execute(script_runs.insert().values(
                id=run_id,
                batch_id=batch_id,
                tenant_id=tenant_id,
                script_name=script_name,
                script_index=idx,
                status="queued",
                total_steps=len(script_def.get("steps", [])),
                journey_def=script_def,
                created_at=now(),
            ))

        # Create isolated context for this run
        ctx = RunContext(run_id, script_name)
        with _ctx_lock:
            _contexts[run_id] = ctx
        register(ctx)

        _log(
            "BATCH", f"[{batch_id}] Script {idx+1}/{len(script_list)}: {script_name}")

        t_start = datetime.now(timezone.utc)
        try:
            # Mark running
            with engine.begin() as conn:
                conn.execute(update(script_runs).where(script_runs.c.id == run_id).values(
                    status="running", started_at=now()
                ))
            ctx.set_status("running")

            success = runner_fn(run_id, script_def, ctx, tenant_id=tenant_id)
            duration = (datetime.now(timezone.utc) -
                        t_start).total_seconds() * 1000

            m = ctx.get_metrics()
            status = "passed" if success else "failed"
            healed = m.get("healedSelectors", 0)
            if healed > 0 and success:
                status = "healed"

            if status in ("passed", "healed"):
                batch_passed += 1
                if status == "healed":
                    batch_healed += 1
            else:
                batch_failed += 1

            with engine.begin() as conn:
                conn.execute(update(script_runs).where(script_runs.c.id == run_id).values(
                    status=status,
                    finished_at=now(),
                    duration_ms=duration,
                    llm_calls=m.get("llmCalls", 0),
                    vision_calls=m.get("visionCalls", 0),
                    healed_steps=healed,
                    failed_steps=m.get("failures", 0),
                ))

            # Increment tenant usage
            increment_usage(tenant_id, date_str, scripts=1,
                            heals=healed, llm=m.get("llmCalls", 0))

            _log("BATCH", f"[{batch_id}] {script_name} → {status.upper()}")

        except Exception as e:
            batch_failed += 1
            _log(
                "BATCH", f"[{batch_id}] {script_name} crashed: {e}", level="error")
            with engine.begin() as conn:
                conn.execute(update(script_runs).where(script_runs.c.id == run_id).values(
                    status="error", error=str(e), finished_at=now()
                ))

        # Update batch counters after each script
        completed = idx + 1
        with engine.begin() as conn:
            conn.execute(update(batches).where(batches.c.id == batch_id).values(
                completed=completed,
                passed=batch_passed,
                healed=batch_healed,
                failed=batch_failed,
            ))

    # Finalise batch
    final_status = "completed" if batch_failed == 0 else (
        "completed" if batch_passed + batch_healed > 0 else "failed"
    )
    with engine.begin() as conn:
        conn.execute(update(batches).where(batches.c.id == batch_id).values(
            status=final_status, finished_at=now()
        ))

    _log("BATCH", f"[{batch_id}] Done — {final_status.upper()} "
                  f"(passed={batch_passed} healed={batch_healed} failed={batch_failed})")


# ── Public API ─────────────────────────────────────────────────────────────────

def _start():
    global _started
    with _start_lock:
        if _started:
            return
        for _ in range(MAX_WORKERS):
            threading.Thread(target=_worker, daemon=True).start()
        atexit.register(lambda: [_batch_queue.put_nowait(None)
                        for _ in range(MAX_WORKERS)])
        _started = True
        _log("BATCH", f"{MAX_WORKERS} batch workers started")


def submit_batch(
    tenant:      dict,
    project_id:  str | None,
    batch_name:  str,
    script_list: list,
    runner_fn:   Callable,
    submitted_by: str = "api",
    environment_id: str | None = None,
    environment_snapshot: dict | None = None,
) -> str:
    """
    Validate tier limits, create batch record, enqueue.
    Returns batch_id.
    """
    _start()

    tenant_id = tenant["id"]
    tier = tenant.get("tier", "free")
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
    date_str = datetime.now().strftime("%Y-%m-%d")

    # Tier limit check
    if limits["scripts_per_day"] != -1:
        used = get_daily_usage(tenant_id, date_str)
        remaining = limits["scripts_per_day"] - used
        if remaining <= 0:
            raise PermissionError(
                f"Daily limit reached ({limits['scripts_per_day']} scripts/day on {tier} tier)"
            )
        if len(script_list) > remaining:
            script_list = script_list[:remaining]
            _log("BATCH", f"Trimmed to {remaining} scripts due to tier limit")

    batch_id = str(uuid.uuid4())[:8]

    with engine.begin() as conn:
        conn.execute(batches.insert().values(
            id=batch_id,
            tenant_id=tenant_id,
            project_id=project_id,
            environment_id=environment_id,
            environment_snapshot=environment_snapshot or {},
            name=batch_name,
            status="queued",
            total_scripts=len(script_list),
            completed=0, passed=0, healed=0, failed=0,
            created_at=now(),
            submitted_by=submitted_by,
        ))

    _batch_queue.put_nowait((batch_id, tenant, script_list, runner_fn))
    _log(
        "BATCH", f"Batch {batch_id} queued — {len(script_list)} scripts, tier={tier}")
    return batch_id


def get_context(run_id: str) -> RunContext | None:
    with _ctx_lock:
        return _contexts.get(run_id)


def queue_depth() -> int:
    return _batch_queue.qsize()
