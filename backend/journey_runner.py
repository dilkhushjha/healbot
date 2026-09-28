"""
journey_runner.py — SaaS per-run journey executor.
Passes tenant_id through to healing engine for isolated memory.
"""
from sqlalchemy import insert
from core.logger import log
from core.database import engine, step_results, heal_events, upsert_step, now
from healing.healing_engine import heal_selector
from driver_factory import get_driver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from datetime import datetime, timezone
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))


WAIT = 8


def _execute(driver, step, selector):
    a = step["action"]
    if a == "wait":
        WebDriverWait(driver, WAIT).until(
            EC.presence_of_element_located((By.XPATH, selector)))
    elif a == "type":
        el = WebDriverWait(driver, WAIT).until(
            EC.presence_of_element_located((By.XPATH, selector)))
        el.clear()
        el.send_keys(step["value"])
    elif a == "click":
        WebDriverWait(driver, WAIT).until(
            EC.element_to_be_clickable((By.XPATH, selector))).click()
    elif a == "assert_url":
        WebDriverWait(driver, WAIT).until(
            lambda d: step["value"] in d.current_url)


def _finish(run_id, sid, status, original, healed, error, t_start, ctx, tenant_id,
            screenshot=None, vision_verdict="unknown", vision_note=""):
    duration = (datetime.now(timezone.utc) - t_start).total_seconds() * 1000
    upsert_step(run_id, sid, tenant_id,
                status=status, healed_selector=healed, error=error,
                duration_ms=duration, finished_at=now(),
                screenshot_path=screenshot,
                vision_verdict=vision_verdict, vision_note=vision_note)
    ctx.push({
        "type": "step", "step_id": sid, "status": status,
        "original_selector": original, "healed_selector": healed,
        "reason": error or "", "vision_verdict": vision_verdict, "vision_note": vision_note,
    })


def run_journey(run_id: str, journey_def: dict, ctx, tenant_id: str = "default") -> bool:
    steps = journey_def["steps"]
    client_id = journey_def.get("client_id") or tenant_id
    journey_name = journey_def.get("name", "unnamed")
    environment = journey_def.get("environment") or {}
    capability = environment.get("runner_capability")

    log("JOURNEY",
        f"[{run_id}] '{journey_name}' — {len(steps)} steps", ctx=ctx)
    if environment:
        log(
            "JOURNEY",
            f"[{run_id}] target={environment.get('project_name', '')}/{environment.get('name', '')} runner={capability.get('name') if capability else 'default'}",
            ctx=ctx,
        )
    driver = get_driver(ctx=ctx, capability=capability)
    success = True

    try:
        for step in steps:
            sid = step["id"]
            desc = step["description"]
            selector = step.get("selector")
            action = step["action"]
            critical = step.get("critical", False)
            intent = step.get("intent")

            log("JOURNEY", f"▶ [{sid}] {desc}", ctx=ctx)
            t_start = now()
            upsert_step(run_id, sid, tenant_id,
                        description=desc, action=action,
                        original_selector=selector or "",
                        status="running", started_at=t_start)

            if step.get("url"):
                driver.get(step["url"])

            if action == "assert_url":
                try:
                    _execute(driver, step, selector)
                    _finish(run_id, sid, "pass", selector,
                            None, None, t_start, ctx, tenant_id)
                    log("JOURNEY", f"✅ [{sid}] URL verified", ctx=ctx)
                except Exception as e:
                    _finish(run_id, sid, "fail", selector, None,
                            str(e), t_start, ctx, tenant_id)
                    ctx.increment("failures")
                    if critical:
                        success = False
                        break
                continue

            try:
                _execute(driver, step, selector)
                _finish(run_id, sid, "pass", selector,
                        None, None, t_start, ctx, tenant_id)
                log("JOURNEY", f"✅ [{sid}] {desc}", ctx=ctx)
                continue
            except (NoSuchElementException, TimeoutException, WebDriverException):
                log("JOURNEY", f"⚠ [{sid}] Healing…", ctx=ctx)
                ctx.increment("failures")

            html = driver.page_source
            result = heal_selector(
                old_selector=selector, new_html=html, driver=driver,
                intent=intent, client_id=client_id,
                tenant_id=tenant_id,
                run_id=run_id, step_id=sid, ctx=ctx,
            )

            with engine.begin() as conn:
                conn.execute(heal_events.insert().values(
                    run_id=run_id, tenant_id=tenant_id, step_id=sid,
                    selector=selector, intent=intent or "",
                    dom_score=result["dom_score"],
                    dom_candidate=result["dom_candidate"],
                    llm_invoked=result["llm_invoked"],
                    llm_candidate=result["llm_candidate"],
                    final_selector=result["healed"],
                    strategy=result["strategy"],
                    success=result["healed"] is not None,
                    created_at=now(),
                ))

            healed = result["healed"]
            if healed:
                try:
                    _execute(driver, step, healed)
                    _finish(run_id, sid, "healed", selector, healed, None,
                            t_start, ctx, tenant_id,
                            screenshot=result["screenshot"],
                            vision_verdict=result["vision_verdict"],
                            vision_note=result["vision_note"])
                    log("JOURNEY", f"✅ [{sid}] Healed → {healed}", ctx=ctx)
                    continue
                except Exception as e:
                    log("JOURNEY",
                        f"❌ [{sid}] Healed selector failed: {e}", level="error", ctx=ctx)

            _finish(run_id, sid, "fail", selector, healed,
                    "Unrecoverable", t_start, ctx, tenant_id)
            log("JOURNEY", f"❌ [{sid}] Could not recover",
                level="error", ctx=ctx)
            if critical:
                success = False
                break
            log("JOURNEY", f"[{sid}] Non-critical — continuing", ctx=ctx)

    finally:
        driver.quit()
        log("JOURNEY", "Driver closed", ctx=ctx)

    final = "passed" if success else "failed"
    ctx.set_status(final)
    log("JOURNEY", f"[{run_id}] {final.upper()}", ctx=ctx)
    return success
