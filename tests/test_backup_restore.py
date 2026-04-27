"""Nightly export and restore behavior for Slice 5."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from falkordb import FalkorDB

from test_bootstrap_safety import ROOT, delete_graph, graph_names

EXPORT = ROOT / "scripts" / "export_nightly.py"
RESTORE = ROOT / "scripts" / "restore_backup.py"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, str(script), "--host", "127.0.0.1", "--port", "6380", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _counts(db: FalkorDB, graph: str) -> tuple[int, int]:
    g = db.select_graph(graph)
    nodes = int(g.query("MATCH (n) RETURN count(n)").result_set[0][0])
    edges = int(g.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0])
    return nodes, edges


def _seed_graph(db: FalkorDB, graph: str) -> None:
    delete_graph(db, graph)
    db.select_graph(graph).query(
        """
        CREATE (a:Person {id: 'a', name: 'Ada', active: true})
        CREATE (b:Person:Engineer {id: 'b', name: 'Bob', score: 7})
        CREATE (a)-[:KNOWS {since: 2024}]->(b)
        """
    )


def test_export_then_restore_verifies_archive_and_manifest(
    db: FalkorDB, tmp_path: Path
) -> None:
    graph = f"backup_{uuid4().hex}"
    _seed_graph(db, graph)

    export = _run(EXPORT, "--datasets", graph, "--output-root", str(tmp_path))

    assert export.returncode == 0, export.stderr
    archives = list(tmp_path.glob(f"{graph}/**/*.cypher.zst"))
    assert len(archives) == 1
    manifest_path = archives[0].with_suffix(archives[0].suffix + ".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["graph"] == graph
    assert manifest["node_count"] == 2
    assert manifest["edge_count"] == 1
    assert manifest["sha256"]

    restore = _run(RESTORE, "--graph", graph, "--archive", str(archives[0]), "--confirm-delete-target")

    assert restore.returncode == 0, restore.stderr
    assert _counts(db, graph) == (manifest["node_count"], manifest["edge_count"])
    delete_graph(db, graph)


def test_restore_rolls_back_when_manifest_counts_do_not_match(
    db: FalkorDB, tmp_path: Path
) -> None:
    graph = f"backup_bad_{uuid4().hex}"
    _seed_graph(db, graph)
    export = _run(EXPORT, "--datasets", graph, "--output-root", str(tmp_path))
    assert export.returncode == 0, export.stderr
    archive = next(tmp_path.glob(f"{graph}/**/*.cypher.zst"))
    manifest_path = archive.with_suffix(archive.suffix + ".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["node_count"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    restore = _run(RESTORE, "--graph", graph, "--archive", str(archive), "--confirm-delete-target")

    assert restore.returncode == 4
    assert graph not in graph_names(db)
