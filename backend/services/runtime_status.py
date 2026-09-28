"""Runtime health and product metadata for Healbot."""
import urllib.request

from core.batch_scheduler import queue_depth
from core.config import (
    API_VERSION,
    ENVIRONMENT,
    LLM_REVIEW_THRESHOLD,
    PRODUCT_NAME,
    PRODUCT_TAGLINE,
)
from healing.llm_providers import provider_descriptor


def llm_status(timeout: float = 0.8) -> dict:
    """Return LLM readiness without coupling UI code to a specific provider."""
    descriptor = provider_descriptor()
    status = {
        "provider": descriptor["provider"],
        "model": descriptor["model"],
        "url": descriptor["url"],
        "review_threshold": LLM_REVIEW_THRESHOLD,
        "ready": bool(descriptor["configured"]),
        "mode": descriptor["mode"],
        "message": "Configured" if descriptor["configured"] else "Missing provider config",
    }
    if descriptor["mode"] != "local":
        if not descriptor["api_key_configured"]:
            status["message"] = "Missing API key"
        elif not descriptor["model"]:
            status["message"] = "Missing model"
        return status

    status["ready"] = False
    status["message"] = "Local LLM is not connected"
    try:
        with urllib.request.urlopen(f"{descriptor['url']}/api/tags", timeout=timeout) as response:
            status["ready"] = response.status < 500
            status["message"] = "Ready" if status["ready"] else f"HTTP {response.status}"
    except Exception as exc:
        status["message"] = str(exc)[:140]
    return status


def product_meta() -> dict:
    return {
        "product": PRODUCT_NAME,
        "tagline": PRODUCT_TAGLINE,
        "environment": ENVIRONMENT,
        "version": API_VERSION,
        "queue_depth": queue_depth(),
        "llm": llm_status(),
    }
