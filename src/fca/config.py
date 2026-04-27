"""Runtime configuration for FCA embedding integration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingConfig:
    endpoint: str = "http://127.0.0.1:11434/v1/embeddings"
    model: str = "bge-m3"
    dimensions: int = 1024
    batch_size: int = 36
    timeout_seconds: float = 30.0


def _env(name: str, fallback: str) -> str:
    return os.getenv(f"FCA_{name}") or os.getenv(name) or fallback


def embedding_config_from_env() -> EmbeddingConfig:
    return EmbeddingConfig(
        endpoint=_env("EMBEDDING_ENDPOINT", EmbeddingConfig.endpoint),
        model=_env("EMBEDDING_MODEL", EmbeddingConfig.model),
        dimensions=int(_env("EMBEDDING_DIMENSIONS", str(EmbeddingConfig.dimensions))),
        batch_size=int(_env("EMBEDDING_BATCH_SIZE", str(EmbeddingConfig.batch_size))),
        timeout_seconds=float(_env("EMBEDDING_TIMEOUT_SECONDS", str(EmbeddingConfig.timeout_seconds))),
    )
