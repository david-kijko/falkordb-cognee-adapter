from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from cognee.infrastructure.databases.graph.graph_db_interface import GraphDBInterface
from cognee.infrastructure.databases.vector.vector_db_interface import VectorDBInterface

from fca.adapter import FalkorCogneeAdapter, ResultList
from fca.exceptions import FalkorQueryError
from fca.roles import Role


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)


class _RawResult:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.result_set = rows or []


class _FakeSession:
    def __init__(self, graph_name: str, failure: Exception | None = None) -> None:
        self.graph_name = graph_name
        self.failure = failure

    def _maybe_raise(self):
        if self.failure is not None:
            raise self.failure

    def execute(self, statement, params=None, *, read_only=False):
        self._maybe_raise()
        if "count(n) AS nodes" in statement and "count(r)" in statement:
            return _RawResult([[0, 0]])
        if "RETURN count(n) = 0" in statement:
            return _RawResult([[True]])
        if "RETURN count(r) > 0" in statement:
            return _RawResult([[False]])
        return _RawResult([])

    def list_graphs(self):
        self._maybe_raise()
        return [self.graph_name]

    def delete_graph(self):
        self._maybe_raise()
        return None


class _FakeVectors:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure

    def _maybe_raise(self):
        if self.failure is not None:
            raise self.failure

    def has_collection(self, collection_name):
        self._maybe_raise()
        return True

    def ensure_index(self, collection_name):
        self._maybe_raise()
        return None

    def dimension(self, collection_name):
        self._maybe_raise()
        return 2

    def drop_all_vector_indexes(self):
        self._maybe_raise()
        return []

    def list_indices(self):
        self._maybe_raise()
        return ResultList([])


class Node:
    pass


class _Point:
    id = "point-1"
    text = "hello"

    def model_dump(self):
        return {"id": self.id, "text": self.text, "type": "IndexSchema"}


class _FakeEmbedding:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure

    async def embed_text(self, texts):
        if self.failure is not None:
            raise self.failure
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


def _adapter(failure: Exception | None = None) -> tuple[FalkorCogneeAdapter, _RecordingSink]:
    sink = _RecordingSink()
    graph_name = f"session_exactly_once_{uuid4().hex}"
    adapter = FalkorCogneeAdapter(
        host="127.0.0.1",
        port=6380,
        password="",
        graph_name=graph_name,
        role=Role.ARCHIE,
        telemetry=sink,
        socket_timeout=0.1,
        connection_timeout=0.1,
    )
    adapter._session = _FakeSession(graph_name, failure=failure)
    adapter._vectors = _FakeVectors(failure=failure)
    adapter.embedding_engine = _FakeEmbedding(failure=failure)
    return adapter, sink


@pytest.mark.asyncio
async def test_success_path_emits_exactly_once_for_every_public_method() -> None:
    adapter, sink = _adapter()
    calls = _method_calls(adapter)
    assert set(calls) == set(_interface_methods())

    for method_name in _interface_methods():
        before = len(sink.events)
        await calls[method_name]()
        emitted = sink.events[before:]
        assert len(emitted) == 1, f"{method_name} emitted {len(emitted)} success events"
        assert emitted[0]["op"] == method_name
        assert emitted[0]["failure_class"] is None


@pytest.mark.asyncio
async def test_failure_path_emits_exactly_once_for_every_public_method() -> None:
    adapter, sink = _adapter(failure=FalkorQueryError("forced failure"))
    calls = _method_calls(adapter)
    assert set(calls) == set(_interface_methods())

    for method_name in _interface_methods():
        before = len(sink.events)
        with pytest.raises(FalkorQueryError):
            await calls[method_name]()
        emitted = sink.events[before:]
        assert len(emitted) == 1, f"{method_name} emitted {len(emitted)} failure events: {emitted}"
        assert emitted[0]["op"] == method_name
        assert emitted[0]["failure_class"] == "query"
