from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest


def test_no_abstract_methods_remain():
    """SP2: zero abstract methods left after FalkorCogneeAdapter implements both interfaces."""
    from fca.adapter import FalkorCogneeAdapter

    assert FalkorCogneeAdapter.__abstractmethods__ == frozenset()


def test_adapter_signatures_match_fixture():
    """SP1/SP6: adapter method signatures match the frozen Cognee 1.0.3 contract."""
    from fca.adapter import FalkorCogneeAdapter

    fixture = json.loads(
        Path("tests/fixtures/cognee_1_0_3_contract.json").read_text(encoding="utf-8")
    )
    for iface in ["graph_db_interface", "vector_db_interface"]:
        for method in fixture[iface]["abstract_methods"]:
            actual = str(inspect.signature(getattr(FalkorCogneeAdapter, method["name"])))
            expected = method["signature"]
            assert actual == expected, (
                f"{method['name']}: actual={actual} expected={expected}"
            )
            assert inspect.iscoroutinefunction(getattr(FalkorCogneeAdapter, method["name"]))


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


@pytest.mark.asyncio
async def test_cognee_snake_case_relationship_round_trip(falkordb_test):
    await falkordb_test.add_node("set", {"type": "TEST_NODE", "name": "set"})
    await falkordb_test.add_node("chunk", {"type": "TEST_NODE", "name": "chunk"})

    await falkordb_test.add_edge("chunk", "set", "belongs_to_set", {"rank": 1})

    assert await falkordb_test.has_edge("chunk", "set", "belongs_to_set") is True
    edges = await falkordb_test.get_edges("chunk")
    assert ("chunk", "set", "BELONGS_TO_SET") in {(s, t, r) for s, t, r, _ in edges}
    assert any(props["relationship_name"] == "belongs_to_set" for *_, props in edges)


@pytest.mark.asyncio
async def test_get_edges_preserves_direction(falkordb_test):
    await falkordb_test.add_nodes([("A", {"type": "TEST_NODE"}), ("B", {"type": "TEST_NODE"})])
    await falkordb_test.add_edge("A", "B", "points_to", {})

    edges = await falkordb_test.get_edges("B")

    assert ("A", "B", "POINTS_TO") in {(source, target, rel) for source, target, rel, _ in edges}
    assert ("B", "A", "POINTS_TO") not in {(source, target, rel) for source, target, rel, _ in edges}
