"""Stable LLM facade used by the healing engine."""
import json
import urllib.error

from core.logger import log
from healing.llm_providers import LLMProviderError, provider_descriptor, query_selector_model


def ask_llm_for_element(context: list, intent: str, ctx=None) -> dict | None:
    """Ask the configured LLM provider to identify the best replacement element."""
    descriptor = provider_descriptor()
    provider = descriptor["provider"]
    model = descriptor["model"] or "no model"
    if ctx:
        ctx.push({
            "type": "llm_activity",
            "phase": "llm_invoked",
            "status": "running",
            "provider": provider,
            "model": model,
            "intent": intent,
            "element_count": len(context),
            "message": f"LLM invoked: {provider}/{model}",
        })
    log(
        "LLM",
        f"LLM USED: provider={provider}, model={model}, intent={intent}, elements={len(context)}",
        ctx=ctx,
    )
    if ctx:
        ctx.increment("llmCalls")

    try:
        parsed = query_selector_model(context, intent)
        log(
            "LLM",
            f"LLM RESULT: provider={provider}, selected_id={parsed.get('id')}, reason={parsed.get('reason', '')}",
            ctx=ctx,
        )
        if ctx:
            ctx.push({
                "type": "llm_activity",
                "phase": "llm_result",
                "status": "completed",
                "provider": provider,
                "model": model,
                "selected_id": parsed.get("id"),
                "reason": parsed.get("reason", ""),
                "message": "LLM returned a selector candidate",
            })
        return parsed
    except LLMProviderError as exc:
        log("LLM", str(exc), level="error", ctx=ctx)
        if ctx:
            ctx.push({
                "type": "llm_activity",
                "phase": "llm_error",
                "status": "error",
                "provider": provider,
                "model": model,
                "message": str(exc),
            })
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        log("LLM", f"{provider} unreachable: {reason}", level="error", ctx=ctx)
        if ctx:
            ctx.push({
                "type": "llm_activity",
                "phase": "llm_error",
                "status": "error",
                "provider": provider,
                "model": model,
                "message": f"{provider} unreachable: {reason}",
            })
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        log("LLM", f"Provider response parse error: {exc}", level="error", ctx=ctx)
        if ctx:
            ctx.push({
                "type": "llm_activity",
                "phase": "llm_error",
                "status": "error",
                "provider": provider,
                "model": model,
                "message": f"Provider response parse error: {exc}",
            })
    return None
