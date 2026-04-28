#!/usr/bin/env python3
"""Restore a FalkorDB graph from a Slice 5 compressed Cypher archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import zstandard

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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    decompressor = zstandard.ZstdDecompressor()
    with archive.open("rb") as compressed:
        with decompressor.stream_reader(compressed) as reader:
            text = reader.read().decode("utf-8")
    for line in text.splitlines():
        statement = line.strip()
        if not statement:
            continue
        if statement.endswith(";"):
            statement = statement[:-1]
        graph.query(statement)


def _swap_staging_to_target(db: FalkorDB, staging_graph: str, target_graph: str) -> None:
    staging = db.select_graph(staging_graph)
    try:
        staging.execute_command("RENAME", staging_graph, target_graph)
    except Exception:
        _delete_graph(db, target_graph)
        staging.copy(target_graph)
        _delete_graph(db, staging_graph)


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
    actual_sha = _sha256(args.archive)
    if actual_sha != manifest.get("sha256"):
        print("archive sha256 mismatch", file=sys.stderr)
        return 5
    lock_path = Path(f"/tmp/falkordb-cognee-adapter.{args.graph}.lock")
    staging_graph = f"{args.graph}__restore_{uuid4().hex}"
    try:
        with writer_lock(lock_path, timeout=5.0):
            db = _connect(args)
            _delete_graph(db, staging_graph)
            try:
                _replay_archive(db, staging_graph, args.archive)
                actual_nodes, actual_edges = _counts(db, staging_graph)
                expected = (int(manifest["node_count"]), int(manifest["edge_count"]))
                if (actual_nodes, actual_edges) != expected:
                    print(
                        "count mismatch: "
                        f"actual=({actual_nodes}, {actual_edges}) expected={expected}; rolled back",
                        file=sys.stderr,
                    )
                    return 4
                _swap_staging_to_target(db, staging_graph, args.graph)
                print(f"restored {args.graph} nodes={actual_nodes} edges={actual_edges}")
                return 0
            except Exception as exc:
                print(f"restore failed before target swap: {exc}", file=sys.stderr)
                return 1
            finally:
                _delete_graph(db, staging_graph)
    except WriterLockBusy as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
