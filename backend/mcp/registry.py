"""Registry for Healbot MCP-style tool surfaces.

The API exposes these definitions so future agents, CI connectors, and IDE
plugins can discover product capabilities without coupling to internal routes.
"""


MCP_TOOLS = [
    {
        "id": "healbot.runs.start",
        "name": "Start automation run",
        "domain": "runs",
        "description": "Create a tenant-scoped run session and live stream.",
        "http": {"method": "POST", "path": "/sessions/start"},
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "framework": {"type": "string"},
                "project_id": {"type": "string"},
                "environment_id": {"type": "string"},
            },
        },
    },
    {
        "id": "healbot.healing.request",
        "name": "Request selector healing",
        "domain": "healing",
        "description": "Analyze a broken selector and return a trusted candidate.",
        "http": {"method": "POST", "path": "/heal"},
        "input_schema": {
            "type": "object",
            "required": ["selector", "html"],
            "properties": {
                "selector": {"type": "string"},
                "html": {"type": "string"},
                "intent": {"type": "string"},
                "session_id": {"type": "string"},
            },
        },
    },
    {
        "id": "healbot.evidence.report",
        "name": "Fetch run evidence",
        "domain": "evidence",
        "description": "Return batch-level execution and healing evidence.",
        "http": {"method": "GET", "path": "/batches/{batch_id}/report"},
        "input_schema": {
            "type": "object",
            "required": ["batch_id"],
            "properties": {"batch_id": {"type": "string"}},
        },
    },
    {
        "id": "healbot.projects.configure",
        "name": "Configure QA project",
        "domain": "configuration",
        "description": "Create projects and environments used by SDK runners.",
        "http": {"method": "POST", "path": "/projects"},
        "input_schema": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
            },
        },
    },
]


def list_tools() -> list[dict]:
    return MCP_TOOLS


def manifest() -> dict:
    return {
        "name": "Healbot MCP Surface",
        "version": "0.1.0",
        "transport": "http",
        "stability": "preview",
        "tools": MCP_TOOLS,
    }
