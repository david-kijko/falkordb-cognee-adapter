"""Graph-per-dataset isolation remains intact after Slice 5."""

from __future__ import annotations

from falkordb import FalkorDB

from fca.isolation import GraphPerDataset
from test_bootstrap_safety import delete_graph, graph_names


def test_delete_one_dataset_does_not_affect_others(db: FalkorDB) -> None:
    isolation = GraphPerDataset()
    keep = "isolation_keep"
    drop = "isolation_drop"
    for name in (keep, drop):
        delete_graph(db, name)
        isolation.graph_for(db, name).query("CREATE (:Sentinel {dataset: $dataset})", {"dataset": name})

    isolation.delete(db, drop)

    assert drop not in graph_names(db)
    assert keep in graph_names(db)
    count = isolation.graph_for(db, keep).query("MATCH (n:Sentinel) RETURN count(n)").result_set
    assert count == [[1]]
    delete_graph(db, keep)
