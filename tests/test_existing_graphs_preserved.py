"""Bootstrap must preserve pre-existing production-style fraud graphs unless named."""

from __future__ import annotations

from falkordb import FalkorDB

from test_bootstrap_safety import ROSTER_GRAPHS, delete_graph, graph_names, run_bootstrap


def _count_nodes(db: FalkorDB, graph: str) -> int:
    return int(db.select_graph(graph).query("MATCH (n) RETURN count(n)").result_set[0][0])


def test_existing_archie_graphs_preserved_and_explicit_fraud_drop_is_scoped(db: FalkorDB) -> None:
    try:
        for name in ("archie_canon_v1", "archie_map_v1"):
            delete_graph(db, name)
            db.select_graph(name).query("CREATE (:FraudSentinel {id: $id})", {"id": name})

        create_result = run_bootstrap("--create-roster")

        assert create_result.returncode == 0, create_result.stderr
        assert _count_nodes(db, "archie_canon_v1") == 1
        assert _count_nodes(db, "archie_map_v1") == 1

        drop_result = run_bootstrap(
            "--drop-graphs", "archie_canon_v1", "--confirm-drop-fraud", "--yes"
        )

        assert drop_result.returncode == 0, drop_result.stderr
        assert "archie_canon_v1" not in graph_names(db)
        assert _count_nodes(db, "archie_map_v1") == 1
    finally:
        for name in (*ROSTER_GRAPHS, "archie_canon_v1", "archie_map_v1"):
            delete_graph(db, name)
