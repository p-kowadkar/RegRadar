"""Vertex AI integration: Pydantic AI model wrapper + embeddings + Check Grounding."""

from __future__ import annotations

import os
from typing import Any

from google import genai
from google.cloud import discoveryengine_v1
from pydantic import BaseModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google_vertex import GoogleVertexProvider

from backend.utils.logging import get_logger

log = get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Pydantic AI provider (lazy singleton)
# ════════════════════════════════════════════════════════════════

_PROVIDER: GoogleVertexProvider | None = None
_GENAI_CLIENT: genai.Client | None = None
_GROUNDING_CLIENT: discoveryengine_v1.GroundedGenerationServiceAsyncClient | None = None


def _get_provider() -> GoogleVertexProvider:
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = GoogleVertexProvider(
            project_id=os.environ["GOOGLE_CLOUD_PROJECT"],
            region=os.environ["GOOGLE_CLOUD_LOCATION"],
        )
        log.info("vertex_ai.provider_initialized")
    return _PROVIDER


def vertex_model(model_name: str | None = None) -> GoogleModel:
    """Returns a Pydantic AI GoogleModel for a Vertex AI Gemini model.

    Args:
        model_name: e.g. "gemini-3.5-flash" or "gemini-3.1-pro".
                    Defaults to env var GEMINI_MODEL_DEFAULT.
    """
    model_name = model_name or os.environ.get("GEMINI_MODEL_DEFAULT", "gemini-3.5-flash")
    return GoogleModel(model_name=model_name, provider=_get_provider())


# ════════════════════════════════════════════════════════════════
# Direct google-genai client (for embeddings + grounded search)
# ════════════════════════════════════════════════════════════════


def _get_genai_client() -> genai.Client:
    global _GENAI_CLIENT
    if _GENAI_CLIENT is None:
        _GENAI_CLIENT = genai.Client(
            vertexai=True,
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ["GOOGLE_CLOUD_LOCATION"],
        )
        log.info("vertex_ai.genai_client_initialized")
    return _GENAI_CLIENT


async def embed_text(
    *,
    text: str,
    model: str | None = None,
    output_dim: int = 768,
) -> list[float]:
    """Embed text via gemini-embedding-001 with Matryoshka truncation.

    output_dim must be one of: 768, 1536, 3072.
    """
    model = model or os.environ.get("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    client = _get_genai_client()
    response = await client.aio.models.embed_content(
        model=model,
        contents=text,
        config={"output_dimensionality": output_dim},
    )
    return response.embeddings[0].values


# ════════════════════════════════════════════════════════════════
# Vertex AI Check Grounding (the Auditor's spine)
# ════════════════════════════════════════════════════════════════


class GroundingCitation(BaseModel):
    source_id: str
    confidence: float
    supporting_text: str


class GroundingResult(BaseModel):
    claim: str
    is_grounded: bool
    overall_confidence: float
    citations: list[GroundingCitation]


async def check_grounding(*, claim: str, sources: list[str]) -> GroundingResult:
    """Call the Vertex AI Check Grounding API to verify a claim against sources.

    Returns a confidence score in [0, 1] and per-citation supporting text.
    Used exclusively by the Auditor agent.
    """
    global _GROUNDING_CLIENT
    if _GROUNDING_CLIENT is None:
        _GROUNDING_CLIENT = discoveryengine_v1.GroundedGenerationServiceAsyncClient()

    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    parent = f"projects/{project}/locations/global"

    request = discoveryengine_v1.CheckGroundingRequest(
        grounding_config=f"{parent}/groundingConfigs/default_grounding_config",
        answer_candidate=claim,
        facts=[
            discoveryengine_v1.GroundingFact(
                fact_text=src,
                attributes={"source_id": f"src_{i}"},
            )
            for i, src in enumerate(sources)
        ],
        grounding_spec=discoveryengine_v1.CheckGroundingSpec(citation_threshold=0.6),
    )

    response = await _GROUNDING_CLIENT.check_grounding(request=request)
    log.info(
        "vertex_ai.grounding_check",
        confidence=response.support_score,
        is_grounded=response.support_score >= 0.65,
        n_citations=len(response.cited_chunks),
    )
    return GroundingResult(
        claim=claim,
        is_grounded=response.support_score >= 0.65,
        overall_confidence=response.support_score,
        citations=[
            GroundingCitation(
                source_id=c.sources[0].source_id if c.sources else "unknown",
                confidence=getattr(c, "score", 0.0),
                supporting_text=getattr(c, "text", ""),
            )
            for c in response.cited_chunks
        ],
    )
