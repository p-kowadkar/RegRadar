"""
Environment variable loader + validator.

Imported at startup. If required vars are missing, raises immediately so the
app refuses to boot in an unconfigured state. This prevents silent failures
during the demo.

USAGE:
    from backend.utils import env
    env.validate()                          # raises if missing required vars
    api_key = env.get("NIMBLE_API_KEY")
    port = env.get_int("APP_PORT", default=8000)
    enabled = env.get_bool("DD_LLMOBS_ENABLED")
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


# Load .env file if present (no-op in production where env is set via system)
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)


# ════════════════════════════════════════════════════════════════
# Required env vars -- app refuses to start if any is missing
# ════════════════════════════════════════════════════════════════

REQUIRED_VARS: list[str] = [
    # Google Cloud / Vertex AI
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_GENAI_USE_VERTEXAI",
    # OpenRouter fallback
    "OPENROUTER_API_KEY",
    # ClickHouse
    "CLICKHOUSE_HOST",
    "CLICKHOUSE_PORT",
    "CLICKHOUSE_USER",
    # password can be empty for local; not in REQUIRED
    # Scraping
    "NIMBLE_API_KEY",
    "FIRECRAWL_API_KEY",
    # Observability
    "DD_API_KEY",
    "DD_SITE",
]

# Optional vars with defaults
DEFAULTS: dict[str, str] = {
    "CLICKHOUSE_PASSWORD": "",
    "CLICKHOUSE_SECURE": "false",
    "CLICKHOUSE_DATABASE": "regradar",
    "DD_SERVICE": "regradar-backend",
    "DD_ENV": "hackathon",
    "DD_LLMOBS_ENABLED": "1",
    "DD_LLMOBS_AGENTLESS_ENABLED": "1",
    "DD_LLMOBS_ML_APP": "regradar",
    "APP_ENV": "development",
    "APP_PORT": "8000",
    "APP_LOG_LEVEL": "INFO",
    "APP_CORS_ORIGINS": "http://localhost:5173,http://localhost:3000",
    "APP_WS_HEARTBEAT_SECONDS": "30",
    "WATCHER_API_POLL_INTERVAL_SECONDS": "900",
    "WATCHER_SCRAPE_INTERVAL_SECONDS": "3600",
    "AGENT_MAX_PER_MESSAGE": "3",
    "AGENT_PRIMARY_THRESHOLD": "0.85",
    "AGENT_SUPPORTING_THRESHOLD": "0.65",
    "AGENT_CROSS_TALK_THRESHOLD": "0.50",
    "AUDITOR_REJECT_BLOCKS_DELIVERY": "true",
}


# ════════════════════════════════════════════════════════════════
# Public API
# ════════════════════════════════════════════════════════════════


def validate() -> None:
    """
    Raise RuntimeError if any required env var is missing.

    Call this at app startup BEFORE importing any integration modules.
    """
    missing = [v for v in REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        raise RuntimeError(
            "Missing required environment variables:\n"
            + "\n".join(f"  - {v}" for v in missing)
            + f"\n\nCopy .env.example to .env and fill them in.\n"
            f"See docs/DEPLOYMENT.md for details."
        )

    # Apply defaults for unset optional vars
    for key, default in DEFAULTS.items():
        if not os.environ.get(key):
            os.environ[key] = default


def get(name: str, default: Optional[str] = None) -> str:
    """Get an env var as string. Raises KeyError if unset and no default."""
    value = os.environ.get(name, default)
    if value is None:
        raise KeyError(f"Env var not set: {name}")
    return value


def get_int(name: str, default: Optional[int] = None) -> int:
    """Get an env var as int."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        if default is None:
            raise KeyError(f"Env var not set: {name}")
        return default
    return int(raw)


def get_float(name: str, default: Optional[float] = None) -> float:
    """Get an env var as float."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        if default is None:
            raise KeyError(f"Env var not set: {name}")
        return default
    return float(raw)


def get_bool(name: str, default: bool = False) -> bool:
    """Get an env var as bool. Truthy strings: true, 1, yes."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.lower() in ("true", "1", "yes", "on")


def get_list(name: str, default: Optional[list[str]] = None, sep: str = ",") -> list[str]:
    """Get a comma-separated env var as list."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default or []
    return [s.strip() for s in raw.split(sep) if s.strip()]
