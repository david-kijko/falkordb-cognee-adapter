from __future__ import annotations

import json
import time
from collections.abc import Callable
from io import StringIO
from typing import Any
from uuid import uuid4

import pytest
from cognee.infrastructure.databases.graph.graph_db_interface import GraphDBInterface
from cognee.infrastructure.databases.vector.vector_db_interface import VectorDBInterface

from fca.adapter import FalkorCogneeAdapter, ResultList
from fca.roles import Role
from fca.telemetry import StdlibSink


REQUIRED_FIELDS = {
    "op",
    "dataset",
    "role",
    "latency_ms",
    "rows_in",
    "rows_out",
    "retries",
    "failure_class",
    "schema_version",
    "ts",
}


class _RawResult:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.result_set = rows or []


class _FakeSession:
    def __init__(self, graph_name: str) -> None:
        self.graph_name = graph_name

    def execute(self, statement, params=None, *, read_only=False):
        if "count(n) AS nodes" in statement and "count(r)" in statement:
            return _RawResult([[0, 0]])
        if "RETURN count(n) = 0" in statement:
            return _RawResult([[True]])
        if "RETURN count(r) > 0" in statement:
            return _RawResult([[False]])
        return _RawResult([])

    def list_graphs(self):
        return [self.graph_name]

    def delete_graph(self):
        return None


class _FakeVectors:
    def has_collection(self, collection_name):
        return True

    def ensure_index(self, collection_name):
        return None

    def dimension(self, collection_name):
        return 2

    def drop_all_vector_indexes(self):
        return []

    def list_indices(self):
        return ResultList([])


class Node:
    pass


class _Point:
    id = "point-1"
    text = "hello"

    def model_dump(self):
        return {"id": self.id, "text": self.text, "type": "IndexSchema"}


class _FakeEmbedding:
    async def embed_text(self, texts):
        return [[0.0, 0.0] for _ in texts]


def _interface_methods() -> list[str]:
    return sorted(GraphDBInterface.__abstractmethods__ | VectorDBInterface.__abstractmethods__)


def _method_calls(adapter: FalkorCogneeAdapter) -> dict[str, Callable[[], Any]]:
    return {
        "add_edge": lambda: adapter.add_edge("a", "b", "REL", {}),
        "add_edges": lambda: adapter.add_edges([("a", "b", "REL", {})]),
        "add_node": lambda: adapter.add_node("a", {"type": "Node"}),
        "add_nodes": lambda: adapter.add_nodes([("a", {"type": "Node"})]),
        "batch_search": lambda: adapter.batch_search("IndexSchema_text", ["x"], 1),
        "create_collection": lambda: adapter.create_collection("IndexSchema_text"),
        "create_data_points": lambda: adapter.create_data_points("IndexSchema_text", [_Point()]),
        "delete_data_points": lambda: adapter.delete_data_points("IndexSchema_text", [uuid4()]),
        "delete_graph": lambda: adapter.delete_graph(),
        "delete_node": lambda: adapter.delete_node("a"),
        "delete_nodes": lambda: adapter.delete_nodes(["a"]),
        "embed_data": lambda: adapter.embed_data(["x"]),
        "get_connections": lambda: adapter.get_connections("a"),
        "get_edges": lambda: adapter.get_edges("a"),
        "get_filtered_graph_data": lambda: adapter.get_filtered_graph_data([]),
        "get_graph_data": lambda: adapter.get_graph_data(),
        "get_graph_metrics": lambda: adapter.get_graph_metrics(),
        "get_neighborhood": lambda: adapter.get_neighborhood(["a"], 1),
        "get_neighbors": lambda: adapter.get_neighbors("a"),
        "get_node": lambda: adapter.get_node("a"),
        "get_nodes": lambda: adapter.get_nodes(["a"]),
        "get_nodeset_subgraph": lambda: adapter.get_nodeset_subgraph(Node, []),
        "has_collection": lambda: adapter.has_collection("IndexSchema_text"),
        "has_edge": lambda: adapter.has_edge("a", "b", "REL"),
        "has_edges": lambda: adapter.has_edges([("a", "b", "REL", {})]),
        "is_empty": lambda: adapter.is_empty(),
        "prune": lambda: adapter.prune(),
        "query": lambda: adapter.query("MATCH (n) RETURN n", {}),
        "retrieve": lambda: adapter.retrieve("IndexSchema_text", []),
        "search": lambda: adapter.search("IndexSchema_text", None, [0.0, 0.0], 1),
    }


def _adapter(stream: StringIO) -> FalkorCogneeAdapter:
    graph_name = f"session_telemetry_{uuid4().hex}"
    adapter = FalkorCogneeAdapter(
        host="127.0.0.1",
        port=6380,
        password="",
        graph_name=graph_name,
        role=Role.ARCHIE,
        telemetry=StdlibSink(stream=stream),
        socket_timeout=0.1,
        connection_timeout=0.1,
    )
    adapter._session = _FakeSession(graph_name)
    adapter._vectors = _FakeVectors()
    adapter.embedding_engine = _FakeEmbedding()
    return adapter


def _events(stream: StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


@pytest.mark.asyncio
async def test_every_public_adapter_method_emits_complete_stdlib_event() -> None:
    stream = StringIO()
    adapter = _adapter(stream)
    calls = _method_calls(adapter)
    assert set(calls) == set(_interface_methods())

    for method_name in _interface_methods():
        before = len(_events(stream))
        started_at = time.time()
        await calls[method_name]()
        emitted = _events(stream)[before:]

        assert len(emitted) == 1, f"{method_name} emitted {len(emitted)} events: {emitted}"
        event = emitted[0]
        assert set(event) == REQUIRED_FIELDS
        assert event["op"] == method_name
        assert event["dataset"] == adapter.graph_name
        assert event["role"] == adapter.role.value
        assert isinstance(event["latency_ms"], float)
        assert event["latency_ms"] >= 0
        assert event["rows_in"] is None or isinstance(event["rows_in"], int)
        assert event["rows_out"] is None or isinstance(event["rows_out"], int)
        assert isinstance(event["retries"], int)
        assert event["retries"] >= 0
        assert event["failure_class"] is None
        assert event["schema_version"] == "1"
        assert isinstance(event["ts"], float)
        assert started_at <= event["ts"] <= time.time()
