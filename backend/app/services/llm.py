"""Model access through Vertex AI Agent Platform.

Two clients are used:

* ``google-genai`` for Gemini models and for embeddings. ``GENAI_BACKEND=api_key``
  calls the Gemini API with a key (handy for local work); ``vertex`` routes the same
  SDK calls through Vertex AI with the Cloud Run service account (recommended in GCP).
* ``anthropic.AsyncAnthropicVertex`` for Claude models served by Vertex AI.

``LLM_PROVIDER=mock`` returns deterministic output and hash-based embeddings so the
whole pipeline runs offline.
"""

import hashlib
import logging
from abc import ABC, abstractmethod
from functools import lru_cache

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class LLMClient(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Return the model's text reply to ``prompt``."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""


class MockLLMClient(LLMClient):
    def __init__(self, dim: int) -> None:
        self._dim = dim

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        preview = prompt.strip().replace("\n", " ")[:300]
        return f"[mock-llm] {preview}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_vector(text) for text in texts]

    def _hash_vector(self, text: str) -> list[float]:
        # sha256 is stable across processes (unlike hash()), so vectors are reproducible.
        digest = hashlib.sha256(text.lower().encode("utf-8")).digest()
        return [(digest[i % len(digest)] - 127.5) / 127.5 for i in range(self._dim)]


class GenAIClient(LLMClient):
    """Gemini generation and embeddings via google-genai."""

    def __init__(self, client, model: str, embedding_model: str, dim: int, max_tokens: int):
        self._client = client
        self._model = model
        self._embedding_model = embedding_model
        self._dim = dim
        self._max_tokens = max_tokens

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        from google.genai import types

        config = types.GenerateContentConfig(
            max_output_tokens=self._max_tokens,
            system_instruction=system_prompt or None,
        )
        response = await self._client.aio.models.generate_content(
            model=self._model, contents=prompt, config=config
        )
        return response.text or ""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from google.genai import types

        response = await self._client.aio.models.embed_content(
            model=self._embedding_model,
            contents=texts,
            config=types.EmbedContentConfig(output_dimensionality=self._dim),
        )
        return [item.values for item in response.embeddings]


class ClaudeVertexClient(LLMClient):
    """Claude on Vertex AI for generation; embeddings are delegated to Gemini."""

    def __init__(self, project_id: str, location: str, model: str, max_tokens: int, embedder):
        from anthropic import AsyncAnthropicVertex

        self._client = AsyncAnthropicVertex(project_id=project_id, region=location)
        self._model = model
        self._max_tokens = max_tokens
        self._embedder = embedder

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        kwargs: dict = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        message = await self._client.messages.create(**kwargs)
        return "".join(block.text for block in message.content if block.type == "text")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self._embedder.embed(texts)


def _build_genai_client(settings: Settings):
    from google import genai

    if settings.genai_backend == "vertex":
        return genai.Client(
            vertexai=True, project=settings.gcp_project_id, location=settings.gcp_location
        )
    api_key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
    return genai.Client(api_key=api_key)


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "mock":
        logger.warning("LLM_PROVIDER=mock: responses are deterministic stubs, not real models")
        return MockLLMClient(settings.embedding_dim)

    genai_client = _build_genai_client(settings)
    embedder = GenAIClient(
        genai_client,
        model=settings.gemini_model,
        embedding_model=settings.embedding_model,
        dim=settings.embedding_dim,
        max_tokens=settings.llm_max_output_tokens,
    )
    if settings.llm_provider == "gemini":
        logger.info(
            "LLM provider: Gemini (%s, backend=%s)", settings.gemini_model, settings.genai_backend
        )
        return embedder

    logger.info("LLM provider: Claude on Vertex AI (%s)", settings.claude_model)
    return ClaudeVertexClient(
        project_id=settings.gcp_project_id,
        location=settings.gcp_location,
        model=settings.claude_model,
        max_tokens=settings.llm_max_output_tokens,
        embedder=embedder,
    )


@lru_cache
def get_llm_client() -> LLMClient:
    return build_llm_client(get_settings())
