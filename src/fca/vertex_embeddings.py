"""Vertex AI task-typed embedding backend."""

from __future__ import annotations

from typing import Any

import httpx

from fca.config import EmbeddingConfig, embedding_config_from_env
from fca.embedding_protocol import EmbeddingQueryMode
from fca.exceptions import FalkorEmbeddingError

_MODE_TO_CONFIG_FIELD = {
    "search": "vertex_query_task",
    "qa": "vertex_query_task",
    "fact_check": "vertex_verify_task",
    "code": "vertex_code_task",
}


class VertexEmbeddingEngine:
    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        self.config = config or embedding_config_from_env()

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts, task_type=self.config.vertex_document_task)

    async def embed_query(
        self,
        text: str,
        *,
        mode: EmbeddingQueryMode = "search",
    ) -> list[float]:
        task_type = getattr(self.config, _MODE_TO_CONFIG_FIELD[mode])
        return (await self._embed([text], task_type=task_type))[0]

    async def _embed(self, texts: list[str], *, task_type: str) -> list[list[float]]:
        if not texts:
            return []
        body = {
            "instances": [{"content": text, "task_type": task_type} for text in texts],
            "parameters": {"outputDimensionality": self.config.dimensions},
        }
        headers = {"Content-Type": "application/json"}
        try:
            token = await self._access_token()
        except Exception as exc:  # noqa: BLE001
            raise FalkorEmbeddingError(f"Vertex auth failed: {exc}") from exc
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = self._endpoint()
        if self.config.vertex_api_key:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}key={self.config.vertex_api_key}"
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.post(url, json=body, headers=headers)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise FalkorEmbeddingError(f"Vertex embedding request failed: {exc}") from exc
        return self._vectors_from_vertex_payload(payload, expected_count=len(texts))

    async def _access_token(self) -> str:
        if self.config.vertex_api_key:
            return ""
        try:
            import google.auth
            from google.auth.transport.requests import Request
        except ImportError as exc:  # pragma: no cover - depends on deployment image
            raise RuntimeError("Vertex embeddings require GOOGLE_API_KEY or google-auth ADC") from exc
        credentials, _project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        credentials.refresh(Request())
        return str(credentials.token)

    def _endpoint(self) -> str:
        if self.config.endpoint and self.config.endpoint != EmbeddingConfig.endpoint:
            return self.config.endpoint
        if not self.config.vertex_project and not self.config.vertex_api_key:
            raise FalkorEmbeddingError("Vertex embeddings require GOOGLE_CLOUD_PROJECT or GOOGLE_API_KEY")
        project = self.config.vertex_project or "api-key"
        return (
            f"https://{self.config.vertex_location}-aiplatform.googleapis.com/v1/"
            f"projects/{project}/locations/{self.config.vertex_location}/publishers/google/"
            f"models/{self.config.model}:predict"
        )

    def _vectors_from_vertex_payload(
        self,
        payload: dict[str, Any],
        *,
        expected_count: int,
    ) -> list[list[float]]:
        try:
            predictions = payload["predictions"]
            vectors = [
                [float(value) for value in prediction["embeddings"]["values"]]
                for prediction in predictions
            ]
        except Exception as exc:  # noqa: BLE001
            raise FalkorEmbeddingError(f"Malformed Vertex embedding response: {payload!r}") from exc
        if len(vectors) != expected_count:
            raise FalkorEmbeddingError(
                f"Vertex embedding response count mismatch: got {len(vectors)} for {expected_count} inputs"
            )
        expected = self.get_vector_size()
        for vector in vectors:
            if len(vector) != expected:
                raise FalkorEmbeddingError(
                    f"Vertex embedding dimension mismatch: got {len(vector)}, expected {expected}"
                )
        return vectors

    def get_vector_size(self) -> int:
        return self.config.dimensions

    def get_batch_size(self) -> int:
        return self.config.batch_size
