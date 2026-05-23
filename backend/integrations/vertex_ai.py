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
