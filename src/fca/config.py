"""Runtime configuration for FCA embedding integration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = "ollama"
    endpoint: str = "http://127.0.0.1:11434/v1/embeddings"
    model: str = "bge-m3"
    dimensions: int = 1024
    batch_size: int = 36
    timeout_seconds: float = 30.0
    vertex_project: str = ""
    vertex_location: str = "us-central1"
    vertex_api_key: str = ""
    vertex_document_task: str = "RETRIEVAL_DOCUMENT"
    vertex_query_task: str = "QUESTION_ANSWERING"
    vertex_verify_task: str = "FACT_VERIFICATION"
    vertex_code_task: str = "CODE_RETRIEVAL_QUERY"


def _env(name: str, fallback: str) -> str:
    return os.getenv(f"FCA_{name}") or os.getenv(name) or fallback


def embedding_config_from_env() -> EmbeddingConfig:
    provider = _env("EMBEDDING_PROVIDER", EmbeddingConfig.provider).lower()
    default_model = "gemini-embedding-001" if provider == "vertex" else EmbeddingConfig.model
    default_dimensions = "3072" if provider == "vertex" else str(EmbeddingConfig.dimensions)
    return EmbeddingConfig(
        provider=provider,
        endpoint=_env("EMBEDDING_ENDPOINT", EmbeddingConfig.endpoint),
        model=_env("EMBEDDING_MODEL", default_model),
        dimensions=int(_env("EMBEDDING_DIMENSIONS", default_dimensions)),
        batch_size=int(_env("EMBEDDING_BATCH_SIZE", str(EmbeddingConfig.batch_size))),
        timeout_seconds=float(_env("EMBEDDING_TIMEOUT_SECONDS", str(EmbeddingConfig.timeout_seconds))),
        vertex_project=_env("GOOGLE_CLOUD_PROJECT", EmbeddingConfig.vertex_project),
        vertex_location=_env("GOOGLE_CLOUD_LOCATION", EmbeddingConfig.vertex_location),
        vertex_api_key=os.getenv("GOOGLE_API_KEY", ""),
        vertex_document_task=_env("VERTEX_DOCUMENT_TASK", EmbeddingConfig.vertex_document_task),
        vertex_query_task=_env("VERTEX_QUERY_TASK", EmbeddingConfig.vertex_query_task),
        vertex_verify_task=_env("VERTEX_VERIFY_TASK", EmbeddingConfig.vertex_verify_task),
        vertex_code_task=_env("VERTEX_CODE_TASK", EmbeddingConfig.vertex_code_task),
    )
