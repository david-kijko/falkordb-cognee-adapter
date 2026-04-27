"""Cognee-compatible embedding engine backed by Ollama's OpenAI-compatible API."""

from __future__ import annotations

from typing import Any

import httpx

from fca.config import EmbeddingConfig, embedding_config_from_env
from fca.exceptions import FalkorEmbeddingError


class OllamaEmbeddingEngine:
    """EmbeddingEngine protocol implementation for Ollama bge-m3."""

    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        self.config = config or embedding_config_from_env()

    async def embed_text(self, text: list[str]) -> list[list[float]]:
        if not text:
            return []
        body = {"model": self.config.model, "input": list(text)}
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.post(self.config.endpoint, json=body)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # noqa: BLE001 - expose typed embedding failures
            raise FalkorEmbeddingError(f"Embedding request failed: {exc}") from exc

        try:
            data: list[dict[str, Any]] = sorted(payload["data"], key=lambda item: item.get("index", 0))
            vectors = [[float(value) for value in item["embedding"]] for item in data]
        except Exception as exc:  # noqa: BLE001
            raise FalkorEmbeddingError(f"Malformed embedding response: {payload!r}") from exc

        if len(vectors) != len(text):
            raise FalkorEmbeddingError(
                f"Embedding response count mismatch: got {len(vectors)} for {len(text)} inputs"
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
