"""Embedding engine protocol for symmetric and task-typed backends."""

from __future__ import annotations

from typing import Literal, Protocol

EmbeddingQueryMode = Literal["search", "qa", "fact_check", "code"]


class EmbeddingEngine(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(
        self,
        text: str,
        *,
        mode: EmbeddingQueryMode = "search",
    ) -> list[float]: ...

    def get_vector_size(self) -> int: ...

    def get_batch_size(self) -> int: ...
