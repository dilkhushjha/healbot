"""Persist the latest browser frame for each run.

This is a local-file bridge for refresh/reconnect behavior. In a cloud
deployment this should move behind the artifact storage abstraction.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.config import ARTIFACTS_ROOT


def _frame_path(run_id: str) -> Path:
    safe_run_id = "".join(ch for ch in run_id if ch.isalnum() or ch in {"-", "_"})
    return Path(ARTIFACTS_ROOT) / "live_frames" / f"{safe_run_id}.json"


def save_latest_frame(run_id: str, screenshot: str, captured_at: str = "") -> None:
    if not run_id or not screenshot:
        return
    path = _frame_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "latest_screenshot": screenshot,
                "latest_frame_at": captured_at,
            }
        ),
        encoding="utf-8",
    )


def get_latest_frame(run_id: str) -> dict:
    path = _frame_path(run_id)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
