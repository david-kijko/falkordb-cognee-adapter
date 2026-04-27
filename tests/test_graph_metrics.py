from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_graph_metrics_node_without_edges(falkordb_test):
    await falkordb_test.add_nodes(
        [("m1", {"type": "METRIC_NODE"}), ("m2", {"type": "METRIC_NODE"})]
    )

    metrics = await falkordb_test.get_graph_metrics()

    assert metrics == {"num_nodes": 2, "num_edges": 0}
