"""
Single source of truth for Healbot runtime configuration.

Every setting here is environment-driven so the same codebase can run locally,
in CI, or behind a hosted API gateway without source changes.
"""
import os
from pathlib import Path


def _load_local_env() -> None:
    """Load simple KEY=VALUE files without adding a runtime dependency."""
    config_path = Path(__file__).resolve()
    backend_dir = config_path.parents[1]
    repo_dir = config_path.parents[2]
    for env_path in (repo_dir / ".env", backend_dir / ".env"):
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_local_env()


def _csv_env(name: str, default: str) -> list[str]:
    return [
        item.strip()
        for item in os.environ.get(name, default).split(",")
        if item.strip()
    ]


# Product metadata
PRODUCT_NAME = os.environ.get("HEALBOT_PRODUCT_NAME", "Healbot")
PRODUCT_TAGLINE = os.environ.get(
    "HEALBOT_PRODUCT_TAGLINE",
    "AI-assisted self-healing automation for QA teams",
)
ENVIRONMENT = os.environ.get("HEALBOT_ENV", "local")
API_VERSION = os.environ.get("HEALBOT_API_VERSION", "1.0.0")

# Database
DB_URL = os.environ.get("HEALBOT_DB_URL", "sqlite:///./data/healbot_saas.db")

# HTTP / API
ALLOWED_ORIGINS = _csv_env(
    "HEALBOT_ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
)
ALLOW_CREDENTIALS = os.environ.get("HEALBOT_ALLOW_CREDENTIALS", "true").lower() == "true"

# Queue / Workers
MAX_WORKERS = int(os.environ.get("HEALBOT_WORKERS", 8))
MAX_QUEUED = int(os.environ.get("HEALBOT_MAX_QUEUED", 200))
SCRIPT_TIMEOUT = int(os.environ.get("HEALBOT_SCRIPT_TIMEOUT", 300))

# Healing
CONFIDENCE_THRESHOLD = int(os.environ.get("HEALBOT_CONFIDENCE", 3))
LLM_REVIEW_THRESHOLD = int(os.environ.get("HEALBOT_LLM_REVIEW_THRESHOLD", 7))
LLM_REVIEW_GENERIC_INTENT = os.environ.get(
    "HEALBOT_LLM_REVIEW_GENERIC_INTENT", "true"
).lower() == "true"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3")
LLM_PROVIDER = os.environ.get("HEALBOT_LLM_PROVIDER", "ollama").strip().lower()
LLM_MODEL = os.environ.get("HEALBOT_LLM_MODEL", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.environ.get(
    "OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions"
).strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "").strip()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_BASE_URL = os.environ.get(
    "ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1/messages"
).strip()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_BASE_URL = os.environ.get(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
).strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip()
LLAVA_MODEL = os.environ.get("LLAVA_MODEL", "llava")
LLM_TIMEOUT = int(os.environ.get("HEALBOT_LLM_TIMEOUT", 60))

# Auth
JWT_SECRET = os.environ.get("HEALBOT_JWT_SECRET", "change-me-in-production")
JWT_ALGO = "HS256"
JWT_EXPIRE_H = int(os.environ.get("HEALBOT_JWT_EXPIRE_H", 24))

# Tiers
TIER_LIMITS = {
    "free": {"scripts_per_day": 10, "workers": 1, "history_days": 7},
    "starter": {"scripts_per_day": 100, "workers": 2, "history_days": 30},
    "pro": {"scripts_per_day": 1000, "workers": 4, "history_days": 90},
    "enterprise": {"scripts_per_day": -1, "workers": 8, "history_days": -1},
}

# Paths
ARTIFACTS_ROOT = os.environ.get("HEALBOT_ARTIFACTS", "./artifacts")
MEMORY_ROOT = os.environ.get("HEALBOT_MEMORY", "./memory")
GLOBAL_MEMORY = os.path.join(MEMORY_ROOT, "global_memory.json")
