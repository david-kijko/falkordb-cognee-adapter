from __future__ import annotations

from fca.config import embedding_config_from_env
from fca.embeddings import OllamaEmbeddingEngine, embedding_engine_from_env
from fca.vertex_embeddings import VertexEmbeddingEngine


def test_defaults_keep_ollama_bge_m3(monkeypatch):
    monkeypatch.delenv("FCA_EMBEDDING_PROVIDER", raising=False)
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)

    config = embedding_config_from_env()
    engine = embedding_engine_from_env(config)

    assert config.provider == "ollama"
    assert config.model == "bge-m3"
    assert isinstance(engine, OllamaEmbeddingEngine)


def test_vertex_provider_selects_vertex_engine_and_task_defaults(monkeypatch):
    monkeypatch.setenv("FCA_EMBEDDING_PROVIDER", "vertex")
    monkeypatch.setenv("FCA_EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setenv("FCA_VERTEX_DOCUMENT_TASK", "RETRIEVAL_DOCUMENT")
    monkeypatch.setenv("FCA_VERTEX_QUERY_TASK", "QUESTION_ANSWERING")
    monkeypatch.setenv("FCA_VERTEX_VERIFY_TASK", "FACT_VERIFICATION")

    config = embedding_config_from_env()
    engine = embedding_engine_from_env(config)

    assert config.provider == "vertex"
    assert config.model == "gemini-embedding-001"
    assert config.vertex_document_task == "RETRIEVAL_DOCUMENT"
    assert config.vertex_query_task == "QUESTION_ANSWERING"
    assert config.vertex_verify_task == "FACT_VERIFICATION"
    assert isinstance(engine, VertexEmbeddingEngine)
