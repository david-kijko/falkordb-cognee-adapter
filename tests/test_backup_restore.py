"""Nightly export and restore behavior for Slice 5."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import importlib.util
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from types import ModuleType
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


def _write_manifest(archive: Path, graph: str, *, nodes: int, edges: int) -> None:
    manifest = {
        "graph": graph,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "node_count": nodes,
        "edge_count": edges,
        "sha256": sha256(archive.read_bytes()).hexdigest(),
        "schema_version": "1",
        "exporter_version": "0.1.0",
    }
    archive.with_suffix(archive.suffix + ".manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_zstd_archive(path: Path, text: str) -> None:
    import zstandard

    path.parent.mkdir(parents=True, exist_ok=True)
    compressor = zstandard.ZstdCompressor()
    path.write_bytes(compressor.compress(text.encode("utf-8")))


def _touch(path: Path, when: datetime) -> None:
    timestamp = when.timestamp()
    os.utime(path, (timestamp, timestamp))


def _synthetic_archive(graph_root: Path, when: datetime, name: str | None = None) -> Path:
    hour_name = name if name is not None else f"{when:%H}.cypher.zst"
    archive = graph_root / f"{when:%Y}" / f"{when:%m}" / f"{when:%d}" / hour_name
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(f"{when.isoformat()} {hour_name}".encode("utf-8"))
    _touch(archive, when)
    archive.with_suffix(archive.suffix + ".manifest.json").write_text(
        json.dumps({"snapshot_at": when.isoformat(), "sha256": sha256(archive.read_bytes()).hexdigest()}),
        encoding="utf-8",
    )
    _touch(archive.with_suffix(archive.suffix + ".manifest.json"), when)
    return archive


def _load_script(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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
    before = _counts(db, graph)
    export = _run(EXPORT, "--datasets", graph, "--output-root", str(tmp_path))
    assert export.returncode == 0, export.stderr
    archive = next(tmp_path.glob(f"{graph}/**/*.cypher.zst"))
    manifest_path = archive.with_suffix(archive.suffix + ".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["node_count"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    restore = _run(RESTORE, "--graph", graph, "--archive", str(archive), "--confirm-delete-target")

    assert restore.returncode == 4
    assert _counts(db, graph) == before


def test_restore_rejects_sha256_mismatch(db: FalkorDB, tmp_path: Path) -> None:
    graph = f"backup_sha_{uuid4().hex}"
    _seed_graph(db, graph)
    before = _counts(db, graph)
    export = _run(EXPORT, "--datasets", graph, "--output-root", str(tmp_path))
    assert export.returncode == 0, export.stderr
    archive = next(tmp_path.glob(f"{graph}/**/*.cypher.zst"))
    content = bytearray(archive.read_bytes())
    content[len(content) // 2] ^= 0xFF
    archive.write_bytes(content)

    restore = _run(RESTORE, "--graph", graph, "--archive", str(archive), "--confirm-delete-target")

    assert restore.returncode == 5
    assert "archive sha256 mismatch" in restore.stderr
    assert _counts(db, graph) == before
    delete_graph(db, graph)


def test_restore_decompress_failure_leaves_target_intact(db: FalkorDB, tmp_path: Path) -> None:
    graph = f"backup_bad_zstd_{uuid4().hex}"
    _seed_graph(db, graph)
    before = _counts(db, graph)
    archive = tmp_path / graph / "2026" / "04" / "28" / "01.cypher.zst"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"not a zstandard frame")
    _write_manifest(archive, graph, nodes=2, edges=1)

    restore = _run(RESTORE, "--graph", graph, "--archive", str(archive), "--confirm-delete-target")

    assert restore.returncode != 0
    assert _counts(db, graph) == before
    delete_graph(db, graph)


def test_restore_replay_error_rolls_back_staging(db: FalkorDB, tmp_path: Path) -> None:
    graph = f"backup_bad_cypher_{uuid4().hex}"
    _seed_graph(db, graph)
    before = _counts(db, graph)
    archive = tmp_path / graph / "2026" / "04" / "28" / "01.cypher.zst"
    _write_zstd_archive(
        archive,
        """
        CREATE (:Recovered {id: 'ok'});
        THIS IS NOT CYPHER;
        """,
    )
    _write_manifest(archive, graph, nodes=1, edges=0)

    restore = _run(RESTORE, "--graph", graph, "--archive", str(archive), "--confirm-delete-target")

    assert restore.returncode != 0
    assert _counts(db, graph) == before
    assert not any(name.startswith(f"{graph}__restore_") for name in graph_names(db))
    delete_graph(db, graph)


def test_retention_calendar_buckets(tmp_path: Path) -> None:
    export_nightly = _load_script(EXPORT)

    graph_root = tmp_path / "canon"
    base = datetime(2026, 4, 28, 1, 0, tzinfo=timezone.utc)
    required_hourly = [
        _synthetic_archive(graph_root, base - timedelta(hours=hour), f"{hour:02d}.cypher.zst")
        for hour in range(24)
    ]
    for hour in range(24, 90):
        _synthetic_archive(graph_root, base - timedelta(hours=hour), f"extra-{hour:02d}.cypher.zst")
    for day in range(2, 32):
        _synthetic_archive(graph_root, base - timedelta(days=day), "00.cypher.zst")
    for day in range(2, 32):
        _synthetic_archive(graph_root, base - timedelta(days=day, hours=8), f"dupe-{day:02d}.cypher.zst")
    for week in range(52):
        _synthetic_archive(graph_root, base - timedelta(days=32 + week * 7), "00.cypher.zst")
    for week in range(52):
        _synthetic_archive(
            graph_root,
            base - timedelta(days=32 + week * 7, hours=6),
            f"week-dupe-{week:02d}.cypher.zst",
        )

    assert len(list(graph_root.glob("**/*.cypher.zst"))) >= 200
    assert export_nightly._enforce_retention_and_budget(graph_root, budget_bytes=10**9)

    retained = set(graph_root.glob("**/*.cypher.zst"))
    assert len(retained) == 106
    assert set(required_hourly) <= retained
    daily_days = {
        datetime(
            int(path.parts[-4]),
            int(path.parts[-3]),
            int(path.parts[-2]),
            int(path.name[:2]) if path.name[:2].isdigit() else 0,
            tzinfo=timezone.utc,
        ).date()
        for path in retained
        if base - timedelta(days=32) < datetime(
            int(path.parts[-4]),
            int(path.parts[-3]),
            int(path.parts[-2]),
            int(path.name[:2]) if path.name[:2].isdigit() else 0,
            tzinfo=timezone.utc,
        ) <= base - timedelta(hours=24)
    }
    weekly_weeks = {
        datetime(
            int(path.parts[-4]),
            int(path.parts[-3]),
            int(path.parts[-2]),
            int(path.name[:2]) if path.name[:2].isdigit() else 0,
            tzinfo=timezone.utc,
        ).isocalendar()[:2]
        for path in retained
        if datetime(
            int(path.parts[-4]),
            int(path.parts[-3]),
            int(path.parts[-2]),
            int(path.name[:2]) if path.name[:2].isdigit() else 0,
            tzinfo=timezone.utc,
        ) <= base - timedelta(days=32)
    }
    assert len(daily_days) == 30
    assert len(weekly_weeks) == 52


def test_zstandard_python_lib_available(tmp_path: Path) -> None:
    import zstandard

    source = b"round trip through python zstandard"
    archive = tmp_path / "sample.cypher.zst"
    archive.write_bytes(zstandard.ZstdCompressor().compress(source))

    assert zstandard.ZstdDecompressor().decompress(archive.read_bytes()) == source


def test_export_excludes_ephemeral_datasets(db: FalkorDB, tmp_path: Path) -> None:
    datasets = [
        f"session_{uuid4().hex}",
        f"investigation_{uuid4().hex}",
        "quarantine",
        "ingestion_metadata",
    ]
    for graph in datasets:
        _seed_graph(db, graph)

    export = _run(EXPORT, "--datasets", ",".join(datasets), "--output-root", str(tmp_path))

    assert export.returncode == 0, export.stderr
    for graph in datasets:
        assert not list(tmp_path.glob(f"{graph}/**/*.cypher.zst"))
        assert _counts(db, graph) == (2, 1)
        delete_graph(db, graph)


def test_budget_overrun_does_not_leave_oversized_artifact(db: FalkorDB, tmp_path: Path) -> None:
    graph = f"backup_budget_{uuid4().hex}"
    _seed_graph(db, graph)

    export = _run(EXPORT, "--datasets", graph, "--output-root", str(tmp_path), "--budget-bytes", "1")

    assert export.returncode == 4
    assert "budget exceeded" in export.stderr
    assert not list(tmp_path.glob(f"{graph}/**/*.cypher.zst"))
    assert not list(tmp_path.glob(f"{graph}/**/*.manifest.json"))
    delete_graph(db, graph)
