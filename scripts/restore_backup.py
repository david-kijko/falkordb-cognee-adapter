#!/usr/bin/env python3
"""Restore a FalkorDB graph from a Slice 5 compressed Cypher archive."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from falkordb import FalkorDB  # noqa: E402

from fca.writer_lock import WriterLockBusy, writer_lock  # noqa: E402


def _connect(args: argparse.Namespace) -> FalkorDB:
    password = args.password if args.password is not None else os.getenv("FALKOR_PASSWORD", "")
    return FalkorDB(
        host=args.host or os.getenv("FALKOR_HOST", "127.0.0.1"),
        port=args.port or int(os.getenv("FALKOR_PORT", "6379")),
        password=password or None,
        socket_timeout=10,
        socket_connect_timeout=2,
    )


def _manifest_path(archive: Path) -> Path:
    return archive.with_suffix(archive.suffix + ".manifest.json")


def _counts(db: FalkorDB, graph_name: str) -> tuple[int, int]:
    graph = db.select_graph(graph_name)
    nodes = int(graph.query("MATCH (n) RETURN count(n)").result_set[0][0])
    edges = int(graph.query("MATCH ()-[r]->() RETURN count(r)").result_set[0][0])
    return nodes, edges


def _delete_graph(db: FalkorDB, graph_name: str) -> None:
    try:
        db.select_graph(graph_name).delete()
    except Exception:
        pass


def _replay_archive(db: FalkorDB, graph_name: str, archive: Path) -> None:
    graph = db.select_graph(graph_name)
    proc = subprocess.run(
        ["zstd", "-q", "-dc", str(archive)],
        text=True,
        capture_output=True,
        check=True,
    )
    for line in proc.stdout.splitlines():
        statement = line.strip()
        if not statement:
            continue
        if statement.endswith(";"):
            statement = statement[:-1]
        graph.query(statement)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--graph", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--confirm-delete-target", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.confirm_delete_target or not args.archive.exists():
        print("invalid args: --confirm-delete-target and existing --archive are required", file=sys.stderr)
        return 1
    manifest_path = _manifest_path(args.archive)
    if not manifest_path.exists():
        print(f"manifest missing: {manifest_path}", file=sys.stderr)
        return 3
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    lock_path = Path(f"/tmp/falkordb-cognee-adapter.{args.graph}.lock")
    try:
        with writer_lock(lock_path, timeout=5.0):
            db = _connect(args)
            _delete_graph(db, args.graph)
            _replay_archive(db, args.graph, args.archive)
            actual_nodes, actual_edges = _counts(db, args.graph)
            expected = (int(manifest["node_count"]), int(manifest["edge_count"]))
            if (actual_nodes, actual_edges) != expected:
                _delete_graph(db, args.graph)
                print(
                    "count mismatch: "
                    f"actual=({actual_nodes}, {actual_edges}) expected={expected}; rolled back",
                    file=sys.stderr,
                )
                return 4
            print(f"restored {args.graph} nodes={actual_nodes} edges={actual_edges}")
            return 0
    except WriterLockBusy as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
