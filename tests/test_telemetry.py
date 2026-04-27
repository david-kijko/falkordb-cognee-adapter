from __future__ import annotations

from uuid import uuid4

import pytest
from cognee.infrastructure.databases.graph.graph_db_interface import GraphDBInterface
from cognee.infrastructure.databases.vector.vector_db_interface import VectorDBInterface

from fca.adapter import FalkorCogneeAdapter
from fca.roles import Role


class CaptureSink:
    def __init__(self) -> None:
        self.events = []

    def emit(self, event):
        self.events.append(event)


@pytest.mark.asyncio
async def test_telemetry_all_public_methods_emit_correct_op_name(falkordb_test):
    sink = CaptureSink()
    falkordb_test.telemetry = sink
    methods = sorted(GraphDBInterface.__abstractmethods__ | VectorDBInterface.__abstractmethods__)
    calls = {
        "add_edge": lambda: falkordb_test.add_edge("tel_a", "tel_b", "belongs_to_set", {}),
        "add_edges": lambda: falkordb_test.add_edges([("tel_a", "tel_b", "belongs_to_set", {})]),
        "add_node": lambda: falkordb_test.add_node("tel_a", {"type": "TELEMETRY_NODE"}),
        "add_nodes": lambda: falkordb_test.add_nodes([("tel_a", {"type": "TELEMETRY_NODE"})]),
        "batch_search": lambda: falkordb_test.batch_search("IndexSchema_text", ["x"], 1),
        "create_collection": lambda: falkordb_test.create_collection("IndexSchema_text"),
        "create_data_points": lambda: falkordb_test.create_data_points("IndexSchema_text", []),
        "delete_data_points": lambda: falkordb_test.delete_data_points("IndexSchema_text", [uuid4()]),
        "delete_graph": lambda: falkordb_test.delete_graph(),
        "delete_node": lambda: falkordb_test.delete_node("tel_a"),
        "delete_nodes": lambda: falkordb_test.delete_nodes(["tel_a"]),
        "embed_data": lambda: falkordb_test.embed_data([]),
        "get_connections": lambda: falkordb_test.get_connections("tel_a"),
        "get_edges": lambda: falkordb_test.get_edges("tel_a"),
        "get_filtered_graph_data": lambda: falkordb_test.get_filtered_graph_data([]),
        "get_graph_data": lambda: falkordb_test.get_graph_data(),
        "get_graph_metrics": lambda: falkordb_test.get_graph_metrics(),
        "get_neighborhood": lambda: falkordb_test.get_neighborhood(["tel_a"], 1),
        "get_neighbors": lambda: falkordb_test.get_neighbors("tel_a"),
        "get_node": lambda: falkordb_test.get_node("tel_a"),
        "get_nodes": lambda: falkordb_test.get_nodes(["tel_a"]),
        "get_nodeset_subgraph": lambda: falkordb_test.get_nodeset_subgraph(str, []),
        "has_collection": lambda: falkordb_test.has_collection("IndexSchema_text"),
        "has_edge": lambda: falkordb_test.has_edge("tel_a", "tel_b", "belongs_to_set"),
        "has_edges": lambda: falkordb_test.has_edges([("tel_a", "tel_b", "belongs_to_set", {})]),
        "is_empty": lambda: falkordb_test.is_empty(),
        "prune": lambda: falkordb_test.prune(),
        "query": lambda: falkordb_test.query("RETURN 1", {}),
        "retrieve": lambda: falkordb_test.retrieve("IndexSchema_text", []),
        "search": lambda: falkordb_test.search("IndexSchema_text", None, [0.0, 1.0], 1),
    }
    assert set(calls) == set(methods)

    for method in methods:
        before = len(sink.events)
        try:
            await calls[method]()
        except Exception:
            # Some vector calls are allowed to fail without Ollama/index setup; telemetry must still emit.
            pass
        emitted = sink.events[before:]
        assert len(emitted) == 1, f"{method} emitted {len(emitted)} events: {emitted}"
        assert emitted[0]["op"] == method


@pytest.mark.asyncio
async def test_telemetry_failure_path_emits_failure_class():
    sink = CaptureSink()
    adapter = FalkorCogneeAdapter(
        host="127.0.0.1",
        port=6399,
        password="",
        graph_name=f"missing_{uuid4().hex}",
        role=Role.ARCHIE,
        telemetry=sink,
        socket_timeout=0.1,
        connection_timeout=0.1,
    )

    with pytest.raises(Exception):
        await adapter.query("RETURN 1", {})

    assert len(sink.events) == 1
    assert sink.events[0]["op"] == "query"
    assert sink.events[0]["failure_class"] is not None


@pytest.mark.asyncio
async def test_router_delete_unauthorized_emits_telemetry(monkeypatch):
    from fca.exceptions import WriteAuthorityError
    from fca.router import DatasetRouter

    class FakeFalkorDB:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr("fca.router.FalkorDB", FakeFalkorDB)

    sink = CaptureSink()
    router = DatasetRouter(
        host="127.0.0.1",
        port=6380,
        password="",
        role=Role.ARCHIE,
        telemetry=sink,
    )

    with pytest.raises(WriteAuthorityError):
        await router.delete_dataset("canon")

    assert len(sink.events) == 1
    assert sink.events[0]["op"] == "delete_dataset"
    assert sink.events[0]["failure_class"] == "write_authority"
