"""
healbot/client.py — Universal HealBot Client

Usage (any framework):
    from healbot import HealBot
    hb = HealBot(api_key="hb_live_...", url="http://localhost:8000")
    hb.activate()     # auto-detects + patches the current framework
    # ... run your tests ...
    hb.deactivate()

Or zero-config with pytest:
    pip install healbot-sdk
    connect once in the Healbot dashboard
    pytest
"""

import os
import json
import threading
import urllib.request
import urllib.error
import time
from datetime import datetime

from healbot.config import resolve_api_key, resolve_api_url


class HealBot:
    def __init__(
        self,
        api_key: str = "",
        url: str = "http://localhost:8000",
        verbose: bool = True,
        project_id: str = "",
        environment_id: str = "",
    ):
        self.api_key = resolve_api_key(api_key)
        self.url = resolve_api_url("" if url == "http://localhost:8000" else url)
        self.verbose = verbose
        self.project_id = project_id
        self.environment_id = environment_id

        self._session_id: str | None = None
        self._run_id:     str | None = None   # the script_run id for SSE streaming
        self._batch_id:   str | None = None
        self._adapter = None
        self._lock = threading.Lock()
        self._heals:    list = []
        self._failures: list = []
        self._last_heal_response: dict = {}
        self._last_stream_event_at = 0.0
        self._live_stream_stop = threading.Event()
        self._live_stream_thread = None
        self._live_stream_driver_id = None

        if not self.api_key:
            self._warn(
                "No API key found. Connect in the Healbot dashboard, run "
                "`python -m healbot configure`, set HEALBOT_API_KEY, or pass api_key=."
            )

    # ── Connection ─────────────────────────────────────────────────────────────

    def ping(self) -> bool:
        try:
            urllib.request.urlopen(f"{self.url}/health", timeout=3)
            return True
        except Exception:
            return False

    # ── Session lifecycle ──────────────────────────────────────────────────────

    def start_session(
        self,
        name: str = "",
        framework: str = "unknown",
        project_id: str = "",
        environment_id: str = "",
    ) -> str:
        resp = self._post("/sessions/start", {
            "name": name,
            "framework": framework,
            "project_id": project_id or self.project_id,
            "environment_id": environment_id or self.environment_id,
        })
        if not resp:
            return ""

        self._session_id = resp.get("session_id", "")
        self._run_id = resp.get("run_id", "")
        self._batch_id = resp.get("batch_id", "")
        self.project_id = resp.get("project_id") or self.project_id
        self.environment_id = resp.get("environment_id") or self.environment_id
        self._heals = []
        self._failures = []
        self._live_stream_stop.clear()

        stream_url = resp.get("stream_url", "")
        self._log(
            f"Session started - id={self._session_id} | "
            f"Dashboard: {self.url}/stream/{self._run_id}"
        )
        return self._session_id

    def end_session(self) -> dict:
        if not self._session_id:
            return {}
        self.stop_live_stream()
        resp = self._post("/sessions/end", {"session_id": self._session_id})
        self._log(
            f"Session ended - healed={resp.get('healed', 0)} "
            f"failed={resp.get('failed', 0)} "
            f"heal_rate={resp.get('heal_rate', 0)}%"
        )
        self._session_id = None
        self._run_id = None
        self._batch_id = None
        return resp

    def session_report(self) -> dict:
        with self._lock:
            total = len(self._heals) + len(self._failures)
            return {
                "session_id":     self._session_id,
                "run_id":         self._run_id,
                "batch_id":       self._batch_id,
                "project_id":     self.project_id,
                "environment_id": self.environment_id,
                "total_heals":    len(self._heals),
                "total_failures": len(self._failures),
                "heal_rate":      round(len(self._heals) / total * 100, 1) if total else 0,
                "heals":          list(self._heals),
                "failures":       list(self._failures),
            }

    # ── Core heal ──────────────────────────────────────────────────────────────

    def event(
        self,
        event_type: str = "step",
        status: str = "running",
        description: str = "",
        selector: str = "",
        healed_selector: str = "",
        strategy: str = "",
        llm_used: bool = False,
        screenshot: str = "",
        message: str = "",
    ) -> bool:
        if not self.api_key or not self._session_id:
            return False
        resp = self._post("/sessions/event", {
            "session_id": self._session_id,
            "event_type": event_type,
            "status": status,
            "description": description,
            "selector": selector,
            "healed_selector": healed_selector,
            "strategy": strategy,
            "llm_used": llm_used,
            "screenshot": screenshot,
            "message": message,
        })
        return bool(resp.get("ok"))

    def start_live_stream(self, driver, interval: float = 0.9):
        if not self._session_id or driver is None:
            return
        driver_id = id(driver)
        if (
            self._live_stream_thread
            and self._live_stream_thread.is_alive()
            and self._live_stream_driver_id == driver_id
        ):
            return

        self.stop_live_stream()
        self._live_stream_stop.clear()
        self._live_stream_driver_id = driver_id

        def _loop():
            while self._session_id and not self._live_stream_stop.wait(interval):
                self.stream_browser_frame(driver)

        self._live_stream_thread = threading.Thread(
            target=_loop,
            name="healbot-live-browser-stream",
            daemon=True,
        )
        self._live_stream_thread.start()

    def stop_live_stream(self):
        self._live_stream_stop.set()
        self._live_stream_driver_id = None

    def stream_browser_frame(self, driver):
        if not self._session_id:
            return
        screenshot = ""
        try:
            screenshot = driver.get_screenshot_as_base64()
        except Exception:
            return
        if screenshot:
            self.event(
                event_type="browser_frame",
                status="running",
                description="Live browser frame",
                screenshot=screenshot,
            )

    def stream_lookup(self, driver, status: str, selector: str, description: str = "", force: bool = False, **extra):
        if not self._session_id:
            return
        self.start_live_stream(driver)
        now = time.monotonic()
        if not force and now - self._last_stream_event_at < 1.25:
            return
        self._last_stream_event_at = now
        screenshot = ""
        try:
            screenshot = driver.get_screenshot_as_base64()
        except Exception:
            screenshot = ""
        self.event(
            event_type="step",
            status=status,
            selector=selector,
            description=description or selector,
            screenshot=screenshot,
            **extra,
        )

    def heal(self, selector: str, html: str, intent: str = "", test_name: str = "") -> str | None:
        if not self.api_key:
            return None

        self._last_heal_response = {}
        resp = self._post("/heal", {
            "selector":   selector,
            "html":       html,
            "intent":     intent,
            "test_name":  test_name,
            "session_id": self._session_id or "",
        })
        if not resp:
            return None
        self._last_heal_response = resp
        if resp.get("llm_used"):
            provider = resp.get("llm_provider") or "configured-provider"
            model = resp.get("llm_model") or "configured-model"
            self._log(f"LLM used: {provider}/{model}")

        if resp.get("success"):
            healed = resp["healed"]
            self._log(
                f"Healed [{resp.get('strategy','?')}] "
                f"score={resp.get('dom_score', 0)} | "
                f"{selector[:35]} -> {healed[:35]}"
            )
            with self._lock:
                self._heals.append({
                    "original": selector,
                    "healed":   healed,
                    "strategy": resp.get("strategy"),
                    "test":     test_name,
                })
            return healed
        else:
            self._log(f"Could not heal: {selector[:60]}", level="warn")
            with self._lock:
                self._failures.append(
                    {"selector": selector, "test": test_name})
            return None

    # ── Framework activation ───────────────────────────────────────────────────

    def activate(self, framework: str = "auto"):
        if framework == "auto":
            framework = _detect_framework()
            self._log(f"Auto-detected framework: {framework}")

        if framework == "selenium":
            from healbot.adapters.selenium_adapter import SeleniumAdapter
            self._adapter = SeleniumAdapter(self)
        elif framework == "playwright":
            from healbot.adapters.playwright_adapter import PlaywrightAdapter
            self._adapter = PlaywrightAdapter(self)
        elif framework == "robot":
            from healbot.adapters.robot_adapter import RobotAdapter
            self._adapter = RobotAdapter(self)
        elif framework == "none":
            self._log("No framework patching — use hb.heal() manually")
            return
        else:
            self._warn(
                f"Unknown framework '{framework}' — use hb.heal() manually")
            return

        self._adapter.patch()
        self._log(f"Patched: {framework}")

    def deactivate(self):
        self.stop_live_stream()
        if self._adapter:
            self._adapter.unpatch()
            self._adapter = None
            self._log("Unpatched")

    # ── Internals ──────────────────────────────────────────────────────────────

    def _post(self, path: str, body: dict) -> dict:
        if not self.api_key:
            return {}
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.url}{path}",
            data=data,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            self._warn(f"API {e.code} on {path}: {e.read().decode()[:150]}")
        except urllib.error.URLError as e:
            self._warn(f"Cannot reach HealBot ({e.reason}) — healing skipped")
        except Exception as e:
            self._warn(f"Error: {e}")
        return {}

    def _log(self, msg: str, level: str = "info"):
        if self.verbose:
            prefix = "WARN " if level == "warn" else "INFO "
            print(f"[HealBot] {prefix}{msg}", flush=True)

    def _warn(self, msg: str):
        self._log(msg, level="warn")


def _detect_framework() -> str:
    import importlib
    for name in ["selenium", "playwright", "robot"]:
        try:
            importlib.import_module(name)
            return name
        except ImportError:
            continue
    return "none"
