"""
healing_engine.py - Full self-healing pipeline with per-tenant memory.

Pipeline:
1. Memory
2. DOM heuristic
3. LLM review for low-confidence or ambiguous matches
4. Vision check when a screenshot is available
5. DOM fallback only when there is meaningful evidence
"""
import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from context.element_context_extractor import extract_element_context
from core.config import LLM_REVIEW_GENERIC_INTENT, LLM_REVIEW_THRESHOLD
from core.logger import log
from healing.dom_healer import CONFIDENCE_THRESHOLD, dom_heal
from healing.intent_engine import infer_intent_from_selector
from healing.learning_engine import learn, recall
from healing.llm_reasoner import ask_llm_for_element
from healing.vision_analyzer import analyze_screenshot
from healing.vision_capture import capture_screen


def _xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ", \"'\", ".join(f"'{part}'" for part in parts) + ")"


def _clean(value):
    if value in (None, "", "null", "None"):
        return None
    return str(value)


def _xpath(el: dict) -> str | None:
    if not el:
        return None
    if _clean(el.get("id")):
        return f"//*[@id={_xpath_literal(_clean(el.get('id')))}]"
    if _clean(el.get("name")):
        return f"//*[@name={_xpath_literal(_clean(el.get('name')))}]"
    if _clean(el.get("data_test")):
        return f"//*[@data-test={_xpath_literal(_clean(el.get('data_test')))}]"
    if _clean(el.get("data_testid")):
        return f"//*[@data-testid={_xpath_literal(_clean(el.get('data_testid')))}]"
    if _clean(el.get("aria_label")):
        return f"//*[@aria-label={_xpath_literal(_clean(el.get('aria_label')))}]"
    if _clean(el.get("placeholder")):
        return f"//*[@placeholder={_xpath_literal(_clean(el.get('placeholder')))}]"
    if _clean(el.get("text")) and _clean(el.get("tag")) in {"a", "button", "option"}:
        return f"//{_clean(el.get('tag'))}[normalize-space()={_xpath_literal(_clean(el.get('text')))}]"
    return None


def _vision_check(screenshot, intent, selector, ctx) -> dict:
    if not screenshot:
        return {"vision_verdict": "unknown", "vision_note": "no screenshot"}
    result = analyze_screenshot(screenshot, intent, selector, ctx=ctx)
    return {
        "vision_verdict": result["verdict"],
        "vision_note": result["note"],
    }


def _accept_candidate(result, old_selector, healed, strategy, tenant_id, ctx):
    learn(old_selector, healed, tenant_id=tenant_id, ctx=ctx)
    log("ENGINE", f"Accepted {strategy} heal -> {healed}", ctx=ctx)
    return {**result, "healed": healed, "strategy": strategy}


def heal_selector(
    old_selector: str,
    new_html: str,
    driver=None,
    intent: str | None = None,
    client_id: str | None = None,
    tenant_id: str = "default",
    run_id: str = "default",
    step_id: str = "unknown",
    ctx=None,
) -> dict:
    log("ENGINE", f"Healing: {old_selector}", ctx=ctx)
    if ctx:
        ctx.push({
            "type": "healing_activity",
            "phase": "healing_started",
            "status": "healing",
            "selector": old_selector,
            "message": "Healing started for a broken selector",
            "step_id": step_id,
        })

    result = {
        "healed": None,
        "strategy": None,
        "dom_score": 0,
        "llm_invoked": False,
        "dom_candidate": None,
        "llm_candidate": None,
        "vision_verdict": "unknown",
        "vision_note": "",
        "screenshot": None,
    }

    cached = recall(old_selector, tenant_id=tenant_id)
    if cached:
        log("ENGINE", f"Memory hit -> {cached}", ctx=ctx)
        return {**result, "healed": cached, "strategy": "memory"}

    screenshot = capture_screen(driver, run_id=run_id, ctx=ctx)
    result["screenshot"] = screenshot

    resolved_intent = intent or infer_intent_from_selector(
        old_selector, client_id or tenant_id
    )
    log("INTENT", f"'{resolved_intent}'", ctx=ctx)

    context = extract_element_context(new_html, ctx=ctx)
    if not context:
        log("ENGINE", "No page element context available", level="error", ctx=ctx)
        return result

    dom_el, score = dom_heal(context, resolved_intent, ctx=ctx)
    result["dom_score"] = score
    result["dom_candidate"] = _xpath(dom_el)

    should_review_with_llm = (
        score < CONFIDENCE_THRESHOLD
        or (dom_el is not None and score < LLM_REVIEW_THRESHOLD)
        or (LLM_REVIEW_GENERIC_INTENT and resolved_intent == "interactive web element")
    )

    if dom_el and score >= CONFIDENCE_THRESHOLD and not should_review_with_llm:
        healed = _xpath(dom_el)
        if healed:
            result.update(_vision_check(screenshot, resolved_intent, healed, ctx))
            if result["vision_verdict"] != "rejected":
                return _accept_candidate(result, old_selector, healed, "dom", tenant_id, ctx)
            log("ENGINE", "DOM candidate rejected by vision; asking LLM", level="warning", ctx=ctx)

    log("ENGINE", f"DOM score {score} needs AI review -> LLM", ctx=ctx)
    result["llm_invoked"] = True
    llm_el = ask_llm_for_element(context, resolved_intent, ctx=ctx)
    if llm_el:
        healed = _xpath(llm_el)
        result["llm_candidate"] = healed
        if healed:
            result.update(_vision_check(screenshot, resolved_intent, healed, ctx))
            if result["vision_verdict"] != "rejected":
                return _accept_candidate(result, old_selector, healed, "llm", tenant_id, ctx)
            log("ENGINE", "LLM candidate rejected by vision", level="warning", ctx=ctx)

    if result["dom_candidate"] and score > 0:
        log("ENGINE", f"Using DOM fallback after LLM review, score={score}", level="warning", ctx=ctx)
        return _accept_candidate(result, old_selector, result["dom_candidate"], "dom_fallback", tenant_id, ctx)

    log("ENGINE", "All strategies exhausted", level="error", ctx=ctx)
    return result
