from __future__ import annotations

import inspect
from typing import Any
from uuid import uuid4

import pytest

from fca.adapter import FalkorCogneeAdapter, ResultList
from fca.roles import Role


class _RawResult:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.result_set = rows or []


class _FakeSession:
    def __init__(self, order: list[str], graph_name: str) -> None:
        self.order = order
        self.graph_name = graph_name

    def execute(self, statement, params=None, *, read_only=False):
        self.order.append("driver:execute")
        if "count(n)" in statement and "count(r)" in statement:
            return _RawResult([[0, 0]])
        if "RETURN count(n) = 0" in statement:
            return _RawResult([[True]])
        if "RETURN count(r) > 0" in statement:
            return _RawResult([[False]])
        return _RawResult([])

    def list_graphs(self):
        self.order.append("driver:list_graphs")
        return [self.graph_name]

    def delete_graph(self):
        self.order.append("driver:delete_graph")


class _FakeVectors:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    def has_collection(self, collection_name):
        self.order.append("driver:vectors.has_collection")
        return False

    def ensure_index(self, collection_name):
        self.order.append("driver:vectors.ensure_index")

    def dimension(self, collection_name):
        self.order.append("driver:vectors.dimension")
        return 2

    def drop_all_vector_indexes(self):
        self.order.append("driver:vectors.drop_all_vector_indexes")
        return []

    def list_indices(self):
        self.order.append("driver:vectors.list_indices")
        return ResultList([])


class _FakeEmbedding:
    async def embed_text(self, texts):
        return [[0.0, 0.0] for _ in texts]


@pytest.mark.asyncio
async def test_every_public_method_calls_a_guard(monkeypatch):
    """SP6 invariant: every public adapter method calls one guard before driver use."""
    adapter = FalkorCogneeAdapter(
        host="127.0.0.1",
        port=6380,
        password="",
        graph_name=f"session_guarded_{uuid4().hex}",
        role=Role.ARCHIE,
        socket_timeout=0.1,
        connection_timeout=0.1,
    )

    public_methods = sorted(
        name
        for name, member in FalkorCogneeAdapter.__dict__.items()
        if inspect.iscoroutinefunction(member) and not name.startswith("_")
    )
    calls = {
        "add_edge": lambda: adapter.add_edge("a", "b", "REL", {}),
        "add_edges": lambda: adapter.add_edges([("a", "b", "REL", {})]),
        "add_node": lambda: adapter.add_node("a", {"type": "Node"}),
        "add_nodes": lambda: adapter.add_nodes([("a", {"type": "Node"})]),
        "batch_search": lambda: adapter.batch_search("IndexSchema_text", [], 1),
        "create_collection": lambda: adapter.create_collection("IndexSchema_text"),
        "create_data_points": lambda: adapter.create_data_points("IndexSchema_text", []),
        "create_vector_index": lambda: adapter.create_vector_index("IndexSchema", "text"),
        "delete_data_points": lambda: adapter.delete_data_points("IndexSchema_text", [uuid4()]),
        "delete_graph": lambda: adapter.delete_graph(),
        "delete_node": lambda: adapter.delete_node("a"),
        "delete_nodes": lambda: adapter.delete_nodes(["a"]),
        "embed_data": lambda: adapter.embed_data([]),
        "get_connections": lambda: adapter.get_connections("a"),
        "get_edges": lambda: adapter.get_edges("a"),
        "get_filtered_graph_data": lambda: adapter.get_filtered_graph_data([]),
        "get_graph_data": lambda: adapter.get_graph_data(),
        "get_graph_metrics": lambda: adapter.get_graph_metrics(),
        "get_neighborhood": lambda: adapter.get_neighborhood(["a"], 1),
        "get_neighbors": lambda: adapter.get_neighbors("a"),
        "get_node": lambda: adapter.get_node("a"),
        "get_nodes": lambda: adapter.get_nodes(["a"]),
        "get_nodeset_subgraph": lambda: adapter.get_nodeset_subgraph(str, []),
        "has_collection": lambda: adapter.has_collection("IndexSchema_text"),
        "has_edge": lambda: adapter.has_edge("a", "b", "REL"),
        "has_edges": lambda: adapter.has_edges([("a", "b", "REL", {})]),
        "index_data_points": lambda: adapter.index_data_points("IndexSchema", "text", []),
        "is_empty": lambda: adapter.is_empty(),
        "prune": lambda: adapter.prune(),
        "query": lambda: adapter.query("MATCH (n) RETURN n", {}),
        "retrieve": lambda: adapter.retrieve("IndexSchema_text", []),
        "search": lambda: adapter.search("IndexSchema_text", None, [0.0, 0.0], 1),
    }
    assert set(calls) == set(public_methods)

    for method_name in public_methods:
        order: list[str] = []
        adapter._session = _FakeSession(order, adapter.graph_name)
        adapter._vectors = _FakeVectors(order)
        adapter.embedding_engine = _FakeEmbedding()

        def read_guard(dataset):
            order.append("guard:read")

        def write_guard(dataset):
            order.append("guard:write")

        monkeypatch.setattr(adapter, "_read_guard", read_guard)
        monkeypatch.setattr(adapter, "_write_guard", write_guard)

        try:
            await calls[method_name]()
        except Exception:
            pass

        guard_events = [event for event in order if event.startswith("guard:")]
        assert len(guard_events) == 1, f"{method_name} guard events: {order}"
        first_driver = next(
            (i for i, event in enumerate(order) if event.startswith("driver:")), None
        )
        if first_driver is not None:
            assert order.index(guard_events[0]) < first_driver, f"{method_name} order: {order}"
