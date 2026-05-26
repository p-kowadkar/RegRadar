"""LLM integration for RegRadar agents.

Provider precedence (first match wins):
  1. OPENROUTER_API_KEY  -> OpenRouter (OpenAI-compatible). Useful when
     Gemini's free-tier daily quota is exhausted, or for cost control.
     Default model can be overridden with OPENROUTER_MODEL.
  2. GEMINI_API_KEY      -> Google API-key path via GoogleProvider.
  3. else                -> GoogleVertexProvider (ADC + project + region).

The function is still named `vertex_model()` so the team's agent imports
keep working without code changes; under the hood it now picks whichever
provider has credentials configured.
"""

from __future__ import annotations

import os

from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.google_vertex import GoogleVertexProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from backend.utils.logging import get_logger

log = get_logger(__name__)


_MODEL: Model | None = None


# Map our internal model names to the OpenRouter slug for the same family.
# Override per call by setting OPENROUTER_MODEL in .env.
_OPENROUTER_MODEL_MAP: dict[str, str] = {
    "gemini-2.5-flash": "google/gemini-2.5-flash",
    "gemini-3.5-flash": "google/gemini-2.5-flash",  # team alias -> real
    "gemini-3.1-pro": "google/gemini-2.5-pro",
    "gemini-2.5-pro": "google/gemini-2.5-pro",
}


def vertex_model(model_name: str | None = None) -> Model:
    """Return a Pydantic AI Model bound to whichever provider is configured.

    Resolution:
      OPENROUTER_API_KEY  -> OpenAIChatModel via OpenRouterProvider
      GEMINI_API_KEY      -> GoogleModel via GoogleProvider (api-key path)
      else                -> GoogleModel via GoogleVertexProvider
    """
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    requested = model_name or os.environ.get(
        "GEMINI_MODEL_DEFAULT", "gemini-2.5-flash"
    )

    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if openrouter_key:
        or_model = os.environ.get("OPENROUTER_MODEL") or _OPENROUTER_MODEL_MAP.get(
            requested, requested
        )
        _MODEL = OpenAIChatModel(
            model_name=or_model,
            provider=OpenRouterProvider(api_key=openrouter_key),
        )
        log.info(
            "llm.provider_initialized",
            path="openrouter",
            model=or_model,
            requested=requested,
        )
        return _MODEL

    if gemini_key:
        _MODEL = GoogleModel(
            model_name=requested, provider=GoogleProvider(api_key=gemini_key)
        )
        log.info("llm.provider_initialized", path="gemini_api_key", model=requested)
        return _MODEL

    _MODEL = GoogleModel(
        model_name=requested,
        provider=GoogleVertexProvider(
            project_id=os.environ["GOOGLE_CLOUD_PROJECT"],
            region=os.environ["GOOGLE_CLOUD_LOCATION"],
        ),
    )
    log.info("llm.provider_initialized", path="vertex_adc", model=requested)
    return _MODEL


# ════════════════════════════════════════════════════════════════
# Per-request BYOK factory -- does NOT cache, does NOT mutate _MODEL
# ════════════════════════════════════════════════════════════════


# Locked OpenAI model -- only gpt-5.4-mini is supported for BYOK demos.
# Reasoning model (released March 2026), uses max_completion_tokens internally,
# defaults to medium reasoning_effort, ~$0.40/$1.60 per 1M tokens.
_OPENAI_BYOK_MODEL = "gpt-5.4-mini"


def vertex_model_for_user(
    api_key: str,
    provider: str,
    model_name: str | None = None,
) -> Model:
    """Build a fresh Pydantic AI Model from a user-supplied key.

    Used by the /api/trigger/crawl endpoint when X-User-LLM-Key is present.
    Never touches the module-level _MODEL singleton -- safe to call per
    request without polluting the server's default provider.

    Args:
        api_key: the user's API key.
        provider: one of "openrouter" | "gemini" | "anthropic" | "openai".
        model_name: provider-specific model id.
            - openrouter: required-ish (e.g. "anthropic/claude-sonnet-4.5",
              "google/gemini-2.5-flash"). Falls back to the singleton's mapped
              slug when omitted.
            - openai: IGNORED -- always uses gpt-5.4-mini.
            - gemini: optional override; defaults to GEMINI_MODEL_DEFAULT.

    Raises:
        ValueError on unknown provider or empty OpenRouter model_name when
        no fallback is configured.
    """
    requested = model_name or os.environ.get(
        "GEMINI_MODEL_DEFAULT", "gemini-2.5-flash"
    )
    p = provider.lower().strip()

    if p == "openrouter":
        # If the user supplied an explicit OpenRouter slug, honor it verbatim.
        # Otherwise translate our internal gemini-* name to the provider mapping.
        slug = model_name.strip() if (model_name and model_name.strip()) else _OPENROUTER_MODEL_MAP.get(
            requested, requested
        )
        log.info(
            "llm.byok_model_built",
            path="openrouter",
            model=slug,
            user_specified=bool(model_name),
        )
        return OpenAIChatModel(
            model_name=slug,
            provider=OpenRouterProvider(api_key=api_key),
        )

    if p == "gemini":
        log.info("llm.byok_model_built", path="gemini_api_key", model=requested)
        return GoogleModel(
            model_name=requested,
            provider=GoogleProvider(api_key=api_key),
        )

    if p == "anthropic":
        # User brought a Claude key -- route via OpenRouter for cross-provider compat.
        # Their key is forwarded to Anthropic; OpenRouter doesn't take a cut.
        log.warning(
            "llm.byok_anthropic_unsupported",
            note="Direct Anthropic provider not wired; ask user to use OpenRouter key.",
        )
        raise ValueError(
            "Anthropic BYOK requires routing through OpenRouter. "
            "Use provider=openrouter with an OpenRouter key that includes Anthropic models."
        )

    if p == "openai":
        from pydantic_ai.providers.openai import OpenAIProvider

        # Hardcoded -- public BYOK demo only supports gpt-5.4-mini to keep
        # cost predictable and avoid accidental gpt-5.5 / gpt-5-pro spend.
        log.info(
            "llm.byok_model_built",
            path="openai",
            model=_OPENAI_BYOK_MODEL,
            note="OpenAI BYOK locked to gpt-5.4-mini regardless of model_name",
        )
        return OpenAIChatModel(
            model_name=_OPENAI_BYOK_MODEL,
            provider=OpenAIProvider(api_key=api_key),
        )

    raise ValueError(f"Unknown BYOK LLM provider: {provider}")
