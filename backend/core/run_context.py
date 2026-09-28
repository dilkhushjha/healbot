import threading
from collections import deque
from datetime import datetime


class RunContext:
    def __init__(self, run_id: str, script_name: str = ""):
        self.run_id = run_id
        self.script_name = script_name
        self._lock = threading.Lock()
        self._logs = deque(maxlen=2000)
        self._metrics = {"llmCalls": 0, "visionCalls": 0,
                         "healedSelectors": 0, "failures": 0}
        self._status = "queued"
        self._latest_screenshot = ""
        self._latest_frame_at = ""

    def push(self, entry: dict):
        entry.setdefault("time", datetime.now().strftime("%H:%M:%S"))
        with self._lock:
            if entry.get("screenshot"):
                self._latest_screenshot = entry["screenshot"]
                self._latest_frame_at = entry["time"]
            self._logs.append(entry)

    def get_logs(self, since: int = 0) -> list:
        with self._lock:
            return list(self._logs)[since:]

    def log_count(self) -> int:
        with self._lock:
            return len(self._logs)

    def increment(self, key: str, amount: int = 1):
        with self._lock:
            if key in self._metrics:
                self._metrics[key] += amount

    def get_metrics(self) -> dict:
        with self._lock:
            return dict(self._metrics)

    def set_status(self, status: str):
        with self._lock:
            self._status = status

    def get_status(self) -> str:
        with self._lock:
            return self._status

    def get_snapshot(self) -> dict:
        with self._lock:
            return {
                "metrics": dict(self._metrics),
                "status": self._status,
                "run_id": self.run_id,
                "script_name": self.script_name,
                "log_count": len(self._logs),
                "latest_screenshot": self._latest_screenshot,
                "latest_frame_at": self._latest_frame_at,
            }


_registry: dict = {}
_lock = threading.Lock()


def register(ctx: RunContext):
    with _lock:
        if len(_registry) > 500:
            oldest = next(iter(_registry))
            del _registry[oldest]
        _registry[ctx.run_id] = ctx


def get(run_id: str) -> RunContext | None:
    with _lock:
        return _registry.get(run_id)
