from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from cognee.infrastructure.engine.models.DataPoint import DataPoint

from fca._vector_index import collection_parts
from fca.exceptions import FalkorEmbeddingError


class IndexSchema(DataPoint):
    text: str
    metadata: dict = {"index_fields": ["text"]}
    belongs_to_set: list[str] = []

OLLAMA_URL = "http://127.0.0.1:11434/v1/models"


@pytest.fixture(scope="session")
def ollama_bge_m3_available():
    try:
        response = httpx.get(OLLAMA_URL, timeout=2.0)
        response.raise_for_status()
    except Exception as exc:  # pragma: no cover - depends on local service
        pytest.skip(
            "Ollama OpenAI-compatible API is not reachable at 127.0.0.1:11434; "
            "install/start Ollama and pull bge-m3 before running vector tests "
            f"({exc!r})"
        )
    return True


async def _insert_points(adapter, texts: list[str]) -> list[UUID]:
    ids = [uuid4() for _ in texts]
    points = [IndexSchema(id=ids[i], text=text, belongs_to_set=[]) for i, text in enumerate(texts)]
    await adapter.create_collection("IndexSchema_text", IndexSchema)
    await adapter.create_data_points("IndexSchema_text", points)
    return ids


@pytest.mark.asyncio
async def test_embed_data_ollama_round_trip(falkordb_test, ollama_bge_m3_available):
    vectors = await falkordb_test.embed_data(["hello", "world"])

    assert len(vectors) == 2
    assert all(len(vector) == 1024 for vector in vectors)
    assert all(isinstance(value, float) for vector in vectors for value in vector[:8])


@pytest.mark.asyncio
async def test_create_collection_creates_index(falkordb_test):
    await falkordb_test.create_collection("IndexSchema_text", IndexSchema)

    indices = falkordb_test._session.list_indices().result_set or []
    assert any(row[0] == "INDEX_SCHEMA" and "text_vector" in row[1] for row in indices)
    parts = collection_parts("DocumentChunk_text")
    assert parts.label == "DOCUMENT_CHUNK"
    assert parts.vector_property == "text_vector"


@pytest.mark.asyncio
async def test_prune_actually_drops_index(falkordb_test):
    await falkordb_test.create_collection("IndexSchema_text", IndexSchema)
    assert await falkordb_test.has_collection("IndexSchema_text") is True

    await falkordb_test.prune()

    assert await falkordb_test.has_collection("IndexSchema_text") is False


@pytest.mark.asyncio
async def test_vector_round_trip_query_vector(falkordb_test, ollama_bge_m3_available):
    ids = await _insert_points(falkordb_test, ["alpha vector target", "beta vector distractor"])
    query_vector = (await falkordb_test.embed_data(["alpha vector target"]))[0]

    results = await falkordb_test.search("IndexSchema_text", None, query_vector, 1, include_payload=True)

    assert results
    assert results[0].id == ids[0]
    assert results[0].payload["text"] == "alpha vector target"


@pytest.mark.asyncio
async def test_search_with_payload_returns_payload(falkordb_test, ollama_bge_m3_available):
    await _insert_points(falkordb_test, ["alpha payload", "beta payload"])

    results = await falkordb_test.search("IndexSchema_text", "alpha payload", None, 1, include_payload=True)

    assert results
    assert results[0].payload is not None
    assert results[0].payload["text"] == "alpha payload"
    assert "text_vector" not in results[0].payload


@pytest.mark.asyncio
async def test_batch_search_independent_results(falkordb_test, ollama_bge_m3_available):
    await _insert_points(falkordb_test, ["red apple fruit", "blue ocean water"])

    results = await falkordb_test.batch_search(
        "IndexSchema_text", ["red apple fruit", "blue ocean water"], 1, include_payload=True
    )

    assert len(results) == 2
    assert results[0]
    assert results[1]
    assert results[0][0].id != results[1][0].id
    assert results[0][0].payload["text"] != results[1][0].payload["text"]


@pytest.mark.asyncio
async def test_delete_data_points_removes_from_index(falkordb_test, ollama_bge_m3_available):
    ids = await _insert_points(falkordb_test, ["delete me unique", "keep me unique"])

    await falkordb_test.delete_data_points("IndexSchema_text", [ids[0]])
    deleted_vector = (await falkordb_test.embed_data(["delete me unique"]))[0]
    remaining = await falkordb_test.search("IndexSchema_text", None, deleted_vector, 5, include_payload=True)
    retrieved = await falkordb_test.retrieve("IndexSchema_text", [str(ids[0]), str(ids[1])])

    assert ids[0] not in {result.id for result in remaining}
    assert ids[1] in {result.id for result in retrieved}
    assert ids[0] not in {result.id for result in retrieved}


@pytest.mark.asyncio
async def test_dimension_mismatch_fails_loud(falkordb_test):
    await falkordb_test.create_collection("IndexSchema_text", IndexSchema)

    with pytest.raises(FalkorEmbeddingError):
        await falkordb_test.search("IndexSchema_text", None, [0.0, 1.0], 1)
