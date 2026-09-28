"""Swappable LLM providers for Healbot selector healing.

The rest of Healbot should call query_selector_model() and stay unaware of
whether the model is local Ollama or a hosted API.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from core.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_BASE_URL,
    ANTHROPIC_MODEL,
    GEMINI_API_KEY,
    GEMINI_BASE_URL,
    GEMINI_MODEL,
    HF_BASE_URL,
    HF_MODEL,
    HF_TOKEN,
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_TIMEOUT,
    OLLAMA_MODEL,
    OLLAMA_URL,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
)

SELECTOR_FIELDS = (
    "id",
    "name",
    "data_test",
    "data_testid",
    "aria_label",
    "tag",
    "text",
    "reason",
)

CONTEXT_FIELDS = (
    "id",
    "name",
    "placeholder",
    "tag",
    "type",
    "text",
    "aria_label",
    "data_test",
    "data_testid",
    "role",
    "class",
)


class LLMProviderError(RuntimeError):
    """Raised when the selected LLM provider is missing config or fails."""


def provider_descriptor() -> dict[str, Any]:
    provider = (LLM_PROVIDER or "ollama").lower()
    if provider in {"openai-compatible", "openai_compatible", "chatgpt"}:
        provider = "openai"

    if provider in {"huggingface", "hf"}:
        provider = "huggingface"
        model = LLM_MODEL or HF_MODEL
        return {
            "provider": provider,
            "model": model,
            "url": HF_BASE_URL,
            "endpoint": HF_BASE_URL,
            "mode": "cloud",
            "api_key_configured": bool(HF_TOKEN),
            "configured": bool(HF_TOKEN and model and HF_BASE_URL),
        }

    if provider == "ollama":
        model = LLM_MODEL or OLLAMA_MODEL
        base_url = OLLAMA_URL.replace("/api/generate", "").rstrip("/")
        return {
            "provider": "ollama",
            "model": model,
            "url": base_url,
            "endpoint": OLLAMA_URL,
            "mode": "local",
            "api_key_configured": True,
            "configured": bool(model and OLLAMA_URL),
        }

    if provider == "openai":
        model = LLM_MODEL or OPENAI_MODEL
        return {
            "provider": "openai",
            "model": model,
            "url": OPENAI_BASE_URL,
            "endpoint": OPENAI_BASE_URL,
            "mode": "cloud",
            "api_key_configured": bool(OPENAI_API_KEY),
            "configured": bool(OPENAI_API_KEY and model),
        }

    if provider == "anthropic":
        model = LLM_MODEL or ANTHROPIC_MODEL
        return {
            "provider": "anthropic",
            "model": model,
            "url": ANTHROPIC_BASE_URL,
            "endpoint": ANTHROPIC_BASE_URL,
            "mode": "cloud",
            "api_key_configured": bool(ANTHROPIC_API_KEY),
            "configured": bool(ANTHROPIC_API_KEY and model),
        }

    if provider == "gemini":
        model = LLM_MODEL or GEMINI_MODEL
        return {
            "provider": "gemini",
            "model": model,
            "url": GEMINI_BASE_URL.replace("{model}", model) if model else GEMINI_BASE_URL,
            "endpoint": GEMINI_BASE_URL,
            "mode": "cloud",
            "api_key_configured": bool(GEMINI_API_KEY),
            "configured": bool(GEMINI_API_KEY and model),
        }

    return {
        "provider": provider,
        "model": LLM_MODEL,
        "url": "",
        "endpoint": "",
        "mode": "unknown",
        "api_key_configured": False,
        "configured": False,
    }


def build_selector_prompt(context: list[dict[str, Any]], intent: str) -> str:
    slim = [
        {key: element[key] for key in CONTEXT_FIELDS if element.get(key)}
        for element in context
        if isinstance(element, dict)
    ]

    return f"""You are a web automation expert. A Selenium selector is broken. Find the correct element.

Intent: {intent}

Page elements (JSON):
{json.dumps(slim, indent=2)}

Reply ONLY with a JSON object. No markdown, no code fences, no explanation outside JSON.
Use this shape:
{{
  "id": "<element id or null>",
  "name": "<element name or null>",
  "data_test": "<data-test value or null>",
  "data_testid": "<data-testid or null>",
  "aria_label": "<aria-label or null>",
  "tag": "<tag name or null>",
  "text": "<visible text or null>",
  "reason": "<one sentence why>"
}}"""


def query_selector_model(context: list[dict[str, Any]], intent: str) -> dict[str, Any]:
    descriptor = provider_descriptor()
    provider = descriptor["provider"]
    prompt = build_selector_prompt(context, intent)

    if not descriptor["configured"]:
        raise LLMProviderError(
            f"{provider} provider is not configured. Set provider, model, and API key as needed."
        )

    if provider == "ollama":
        raw = _query_ollama(prompt, descriptor["model"])
    elif provider == "huggingface":
        raw = _query_huggingface(prompt, descriptor["model"])
    elif provider == "openai":
        raw = _query_openai(prompt, descriptor["model"])
    elif provider == "anthropic":
        raw = _query_anthropic(prompt, descriptor["model"])
    elif provider == "gemini":
        raw = _query_gemini(prompt, descriptor["model"])
    else:
        raise LLMProviderError(f"Unsupported LLM provider: {provider}")

    return _normalize_selector_response(parse_json_object(raw))


def parse_json_object(raw: str) -> dict[str, Any]:
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1].strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def _normalize_selector_response(parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        field: parsed.get(field) if parsed.get(field) not in ("", "null") else None
        for field in SELECTOR_FIELDS
    }


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=LLM_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _openai_chat_url() -> str:
    url = OPENAI_BASE_URL.rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


def _query_ollama(prompt: str, model: str) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    data = _post_json(OLLAMA_URL, payload, {})
    return str(data.get("response", "")).strip()


def _query_openai(prompt: str, model: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    data = _post_json(
        _openai_chat_url(),
        payload,
        {"Authorization": f"Bearer {OPENAI_API_KEY}"},
    )
    return str(data["choices"][0]["message"]["content"]).strip()


def _query_huggingface(prompt: str, model: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    data = _post_json(
        HF_BASE_URL,
        payload,
        {"Authorization": f"Bearer {HF_TOKEN}"},
    )
    return str(data["choices"][0]["message"]["content"]).strip()


def _query_anthropic(prompt: str, model: str) -> str:
    payload = {
        "model": model,
        "max_tokens": 800,
        "temperature": 0,
        "system": "Return only valid JSON.",
        "messages": [{"role": "user", "content": prompt}],
    }
    data = _post_json(
        ANTHROPIC_BASE_URL,
        payload,
        {
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
    )
    parts = data.get("content", [])
    return "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()


def _query_gemini(prompt: str, model: str) -> str:
    endpoint = GEMINI_BASE_URL.replace("{model}", urllib.parse.quote(model, safe=""))
    separator = "&" if "?" in endpoint else "?"
    url = f"{endpoint}{separator}{urllib.parse.urlencode({'key': GEMINI_API_KEY})}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }
    data = _post_json(url, payload, {})
    candidates = data.get("candidates", [])
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    return "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
