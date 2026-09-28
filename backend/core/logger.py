from datetime import datetime
import sys


def log(stage: str, message: str, level: str = "info", ctx=None):
    """
    Unified logger. Prints to stdout always.
    If ctx (RunContext) is provided, also pushes to that run's live buffer
    so the dashboard SSE stream picks it up.
    """
    time_str = datetime.now().strftime("%H:%M:%S")
    line = f"[{time_str}] [{stage}] {message}"
    encoding = sys.stdout.encoding or "utf-8"
    print(line.encode(encoding, errors="replace").decode(encoding), flush=True)

    if ctx is not None:
        ctx.push({
            "time":    time_str,
            "stage":   stage,
            "message": message,
            "level":   level,
        })
