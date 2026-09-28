"""
HealBot Python SDK

Wrap any existing Selenium test with one decorator — zero migration cost.

Install:  pip install requests selenium beautifulsoup4
Usage:

    from healbot_sdk import HealBotClient

    hb = HealBotClient(api_key="hb_live_...", base_url="http://localhost:8000")

    # Submit a pre-defined journey JSON
    batch = hb.submit_batch("Sprint 42", scripts=[journey1, journey2, ...])
    batch.wait()   # blocks until done
    print(batch.report())

    # Or wrap your own Selenium driver with auto-healing
    with hb.healing_driver() as driver:
        driver.find_element_healed("//input[@id='broken-id']", intent="username field")
"""

import time
import json
import urllib.request
import urllib.error
from typing import Optional

try:
    from healbot.config import resolve_api_key, resolve_api_url
except Exception:
    resolve_api_key = lambda explicit="": explicit
    resolve_api_url = lambda explicit="": explicit or "http://localhost:8000"


class HealBotClient:
    def __init__(self, api_key: str = "", base_url: str = "http://localhost:8000"):
        self.api_key = resolve_api_key(api_key)
        self.base_url = resolve_api_url("" if base_url == "http://localhost:8000" else base_url)
        if not self.api_key:
            raise ValueError(
                "No Healbot API key found. Connect in the dashboard, run "
                "`python -m healbot configure`, set HEALBOT_API_KEY, or pass api_key."
            )
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }

    def _request(self, method: str, path: str, body: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(
            url, data=data, headers=self._headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HealBot API {e.code}: {e.read().decode()}")

    # ── Batch submission ──────────────────────────────────────────────────────
    def submit_batch(
        self,
        name:       str,
        scripts:    list,
        project_id: Optional[str] = None,
        environment_id: Optional[str] = None,
    ) -> "Batch":
        """Submit a list of journey dicts as a batch."""
        payload = {"name": name, "scripts": scripts}
        if project_id:
            payload["project_id"] = project_id
        if environment_id:
            payload["environment_id"] = environment_id
        resp = self._request("POST", "/batches", payload)
        return Batch(resp["batch_id"], self)

    # ── Direct queries ────────────────────────────────────────────────────────
    def list_batches(self, limit: int = 20) -> list:
        return self._request("GET", f"/batches?limit={limit}")

    def list_projects(self) -> list:
        return self._request("GET", "/projects")

    def get_batch(self, batch_id: str) -> dict:
        return self._request("GET", f"/batches/{batch_id}")

    def batch_report(self, batch_id: str) -> dict:
        return self._request("GET", f"/batches/{batch_id}/report")

    def analytics(self, days: int = 30) -> dict:
        return self._request("GET", f"/analytics/overview?days={days}")

    def flakiness(self, limit: int = 20) -> list:
        return self._request("GET", f"/analytics/flakiness?limit={limit}")

    def register_intent_map(self, mappings: list) -> dict:
        return self._request("POST", "/intent-maps", {"mappings": mappings})

    # ── Health check ──────────────────────────────────────────────────────────
    def ping(self) -> bool:
        try:
            resp = self._request("GET", "/health")
            return resp.get("status") == "ok"
        except Exception:
            return False


class Batch:
    """Handle to a submitted batch. Provides wait() and report()."""

    def __init__(self, batch_id: str, client: HealBotClient):
        self.batch_id = batch_id
        self._client = client

    def status(self) -> dict:
        return self._client.get_batch(self.batch_id)

    def wait(self, poll_interval: float = 2.0, timeout: float = 3600.0) -> dict:
        """Block until batch completes or timeout. Returns final batch dict."""
        start = time.time()
        while True:
            if time.time() - start > timeout:
                raise TimeoutError(
                    f"Batch {self.batch_id} timed out after {timeout}s")
            data = self.status()
            status = data.get("status", "queued")
            print(f"[HealBot] Batch {self.batch_id}: {status} "
                  f"({data.get('completed',0)}/{data.get('total_scripts',0)})", flush=True)
            if status in ("completed", "failed", "cancelled"):
                return data
            time.sleep(poll_interval)

    def report(self) -> dict:
        return self._client.batch_report(self.batch_id)

    def __repr__(self):
        return f"<HealBot Batch id={self.batch_id}>"
