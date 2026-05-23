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
    # Google Cloud / Vertex AI -- the LLM workhorse
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_GENAI_USE_VERTEXAI",
    # OpenRouter -- LLM fallback for resilience
    "OPENROUTER_API_KEY",
    # ClickHouse -- single data store for everything
    "CLICKHOUSE_HOST",
    "CLICKHOUSE_PORT",
    "CLICKHOUSE_USER",
    # CLICKHOUSE_PASSWORD can be empty for local; not required
    # Nimble -- regulatory scraping (primary)
    "NIMBLE_API_KEY",
    # Firecrawl -- silent fallback scraper
    "FIRECRAWL_API_KEY",
    # Datadog -- LLM observability + control breach alerts
    "DD_API_KEY",
    "DD_SITE",
    # Senso -- cited.md publishing (required for prize track)
    "SENSO_API_KEY",
    # x402 -- monetization rail (required for "Monetize" demo beat)
    # Optional vars below; not in REQUIRED to keep the app bootable without them
]

# Optional vars with defaults (auto-applied if unset)
DEFAULTS: dict[str, str] = {
    # ClickHouse
    "CLICKHOUSE_PASSWORD": "",
    "CLICKHOUSE_SECURE": "false",
    "CLICKHOUSE_DATABASE": "regradar",
    "CLICKHOUSE_PORT": "8123",
    # Model selection
    "GEMINI_MODEL_DEFAULT": "gemini-3.5-flash",
    "GEMINI_MODEL_REASONING": "gemini-3.1-pro",
    "GEMINI_EMBEDDING_MODEL": "gemini-embedding-001",
    # OpenRouter
    "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    # Datadog
    "DD_SERVICE": "regradar-backend",
    "DD_ENV": "hackathon",
    "DD_LLMOBS_ENABLED": "1",
    "DD_LLMOBS_AGENTLESS_ENABLED": "1",
    "DD_LLMOBS_ML_APP": "regradar",
    # Senso
    "SENSO_BASE_URL": "https://apiv2.senso.ai",
    "SENSO_PUBLISH_NAMESPACE": "regradar",
    # x402 (defaults to base mainnet; switch to base-sepolia for testnet)
    "X402_FACILITATOR_URL": "https://x402.org/facilitator",
    "X402_NETWORK": "base",
    "X402_PRICE_USDC_PER_BRIEF": "0.001",
    # App
    "APP_ENV": "development",
    "APP_PORT": "8000",
    "APP_LOG_LEVEL": "INFO",
    "APP_CORS_ORIGINS": "http://localhost:5173,http://localhost:3000",
    "APP_WS_HEARTBEAT_SECONDS": "30",
    # Agents (the 4: Policy Crawler, Impact Analysis, Auditor, Monitoring)
    "POLICY_CRAWLER_INTERVAL_SECONDS": "3600",
    "MONITORING_AGENT_INTERVAL_SECONDS": "86400",
    "EVENT_POLLER_INTERVAL_MS": "500",
    "IMPACT_AGENT_TIMEOUT_SECONDS": "30",
    "AUDITOR_TIMEOUT_SECONDS": "15",
    "AUDITOR_REJECT_BLOCKS_PUBLISH": "true",
    "AUDITOR_APPROVE_THRESHOLD": "0.85",
    "AUDITOR_WARN_THRESHOLD": "0.65",
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
            + "\n\nCopy .env.example to .env and fill them in.\n"
              "See docs/DEPLOYMENT.md for details."
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
    """Get an env var as bool. Truthy strings: true, 1, yes, on."""
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
