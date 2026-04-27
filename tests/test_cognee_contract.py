from __future__ import annotations

import inspect

import pytest
from cognee.infrastructure.databases.graph.graph_db_interface import GraphDBInterface
from cognee.infrastructure.databases.vector.vector_db_interface import VectorDBInterface


def test_no_abstract_methods_remain():
    """SP2: zero abstract methods left after FalkorCogneeAdapter implements both interfaces."""
    from fca.adapter import FalkorCogneeAdapter

    assert FalkorCogneeAdapter.__abstractmethods__ == frozenset()


def test_implements_all_21_graph_methods():
    """SP1: GraphDBInterface conformance."""
    from fca.adapter import FalkorCogneeAdapter

    graph_methods = GraphDBInterface.__abstractmethods__
    assert len(graph_methods) == 21
    missing = {name for name in graph_methods if not callable(getattr(FalkorCogneeAdapter, name, None))}
    assert missing == set()
    assert all(inspect.iscoroutinefunction(getattr(FalkorCogneeAdapter, name)) for name in graph_methods)


def test_implements_all_9_vector_methods():
    """SP1: VectorDBInterface conformance."""
    from fca.adapter import FalkorCogneeAdapter

    vector_methods = VectorDBInterface.__abstractmethods__
    assert len(vector_methods) == 9
    missing = {name for name in vector_methods if not callable(getattr(FalkorCogneeAdapter, name, None))}
    assert missing == set()
    assert all(inspect.iscoroutinefunction(getattr(FalkorCogneeAdapter, name)) for name in vector_methods)


@pytest.mark.asyncio
async def test_behavioral_round_trip(falkordb_test):
    """SP-behavioral: add_nodes -> get_neighborhood(depth=2) -> delete_graph round-trip."""
    await falkordb_test.add_nodes(
        [
            ("left", {"type": "TEST_NODE", "name": "left"}),
            ("middle", {"type": "TEST_NODE", "name": "middle"}),
            ("right", {"type": "TEST_NODE", "name": "right"}),
        ]
    )
    await falkordb_test.add_edges(
        [
            ("left", "middle", "LINKS_TO", {"weight": 1}),
            ("middle", "right", "LINKS_TO", {"weight": 2}),
        ]
    )

    nodes, edges = await falkordb_test.get_neighborhood(["middle"], depth=2)

    assert {node_id for node_id, _ in nodes} == {"left", "middle", "right"}
    assert {(src, dst, rel) for src, dst, rel, _ in edges} == {
        ("left", "middle", "LINKS_TO"),
        ("middle", "right", "LINKS_TO"),
    }

    await falkordb_test.delete_graph()
    assert await falkordb_test.is_empty()
