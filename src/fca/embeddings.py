"""Embedding engines and provider selection for FCA."""

from __future__ import annotations

from typing import Any

import httpx

from fca.config import EmbeddingConfig, embedding_config_from_env
from fca.embedding_protocol import EmbeddingQueryMode
from fca.exceptions import FalkorEmbeddingError


class OllamaEmbeddingEngine:
    """EmbeddingEngine implementation for Ollama's OpenAI-compatible API."""

    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        self.config = config or embedding_config_from_env()

    async def embed_text(self, text: list[str]) -> list[list[float]]:
        return await self.embed_documents(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        body = {"model": self.config.model, "input": list(texts)}
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.post(self.config.endpoint, json=body)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # noqa: BLE001 - expose typed embedding failures
            raise FalkorEmbeddingError(f"Embedding request failed: {exc}") from exc

        return self._vectors_from_openai_payload(payload, expected_count=len(texts))

    async def embed_query(
        self,
        text: str,
        *,
        mode: EmbeddingQueryMode = "search",
    ) -> list[float]:
        _ = mode
        return (await self.embed_documents([text]))[0]

    def _vectors_from_openai_payload(self, payload: dict[str, Any], *, expected_count: int) -> list[list[float]]:
        try:
            data: list[dict[str, Any]] = sorted(payload["data"], key=lambda item: item.get("index", 0))
            vectors = [[float(value) for value in item["embedding"]] for item in data]
        except Exception as exc:  # noqa: BLE001
            raise FalkorEmbeddingError(f"Malformed embedding response: {payload!r}") from exc

        if len(vectors) != expected_count:
            raise FalkorEmbeddingError(
                f"Embedding response count mismatch: got {len(vectors)} for {expected_count} inputs"
            )
        expected = self.get_vector_size()
        for vector in vectors:
            if len(vector) != expected:
                raise FalkorEmbeddingError(
                    f"Embedding dimension mismatch: got {len(vector)}, expected {expected}"
                )
        return vectors

    def get_vector_size(self) -> int:
        return self.config.dimensions

    def get_batch_size(self) -> int:
        return self.config.batch_size


def embedding_engine_from_env(config: EmbeddingConfig | None = None):
    config = config or embedding_config_from_env()
    if config.provider == "vertex":
        from fca.vertex_embeddings import VertexEmbeddingEngine

        return VertexEmbeddingEngine(config)
    if config.provider == "ollama":
        return OllamaEmbeddingEngine(config)
    raise FalkorEmbeddingError(f"Unsupported embedding provider: {config.provider}")
