from __future__ import annotations

import pytest

from fca.config import EmbeddingConfig
from fca.vertex_embeddings import VertexEmbeddingEngine


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeAsyncClient:
    calls = []

    def __init__(self, *, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *, json, headers):
        self.calls.append({"url": url, "json": json, "headers": headers})
        predictions = [
            {"embeddings": {"values": [0.1, 0.2, 0.3]}}
            for _instance in json["instances"]
        ]
        return FakeResponse({"predictions": predictions})


@pytest.mark.asyncio
async def test_vertex_documents_use_retrieval_document_task(monkeypatch):
    FakeAsyncClient.calls = []
    monkeypatch.setattr("fca.vertex_embeddings.httpx.AsyncClient", FakeAsyncClient)
    config = EmbeddingConfig(
        provider="vertex",
        model="gemini-embedding-001",
        dimensions=3,
        vertex_project="archie-project",
        vertex_api_key="test-key",
    )
    engine = VertexEmbeddingEngine(config)

    vectors = await engine.embed_documents(["node text"])

    assert vectors == [[0.1, 0.2, 0.3]]
    assert FakeAsyncClient.calls[0]["json"]["instances"] == [
        {"content": "node text", "task_type": "RETRIEVAL_DOCUMENT"}
    ]


@pytest.mark.asyncio
async def test_vertex_queries_use_qa_and_fact_verification_tasks(monkeypatch):
    FakeAsyncClient.calls = []
    monkeypatch.setattr("fca.vertex_embeddings.httpx.AsyncClient", FakeAsyncClient)
    config = EmbeddingConfig(
        provider="vertex",
        model="gemini-embedding-001",
        dimensions=3,
        vertex_project="archie-project",
        vertex_api_key="test-key",
    )
    engine = VertexEmbeddingEngine(config)

    qa_vector = await engine.embed_query("how should we split services?", mode="qa")
    verify_vector = await engine.embed_query("claim to verify", mode="fact_check")

    assert qa_vector == [0.1, 0.2, 0.3]
    assert verify_vector == [0.1, 0.2, 0.3]
    assert FakeAsyncClient.calls[0]["json"]["instances"][0]["task_type"] == "QUESTION_ANSWERING"
    assert FakeAsyncClient.calls[1]["json"]["instances"][0]["task_type"] == "FACT_VERIFICATION"
