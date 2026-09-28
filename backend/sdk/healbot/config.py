"""Local Healbot profile discovery for SDKs and test runners."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_API_URL = "http://localhost:8000"
APP_DIR_NAME = "Healbot"
PROFILE_FILE = "profile.json"


def profile_path() -> Path:
    override = os.environ.get("HEALBOT_PROFILE")
    if override:
        return Path(override).expanduser()

    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_DIR_NAME / PROFILE_FILE

    return Path.home() / ".healbot" / PROFILE_FILE


def load_profile() -> dict[str, Any]:
    path = profile_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_profile(api_key: str, api_url: str = DEFAULT_API_URL, dashboard_url: str = "") -> Path:
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "api_key": api_key.strip(),
        "api_url": (api_url or DEFAULT_API_URL).rstrip("/"),
        "dashboard_url": dashboard_url.rstrip("/") if dashboard_url else "",
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def resolve_api_key(explicit: str = "") -> str:
    return (
        explicit
        or os.environ.get("HEALBOT_API_KEY", "")
        or load_profile().get("api_key", "")
    ).strip()


def resolve_api_url(explicit: str = "") -> str:
    return (
        explicit
        or os.environ.get("HEALBOT_API_URL", "")
        or os.environ.get("HEALBOT_URL", "")
        or load_profile().get("api_url", "")
        or DEFAULT_API_URL
    ).rstrip("/")
