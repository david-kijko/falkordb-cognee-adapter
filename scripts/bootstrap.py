#!/usr/bin/env python3
"""Bootstrap Archie dataset graphs and explicitly-scoped graph drops."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from falkordb import FalkorDB  # noqa: E402

from fca.datasets import CANON_DATASETS  # noqa: E402

try:  # pragma: no cover - redis import shape is environment-dependent
    from redis.exceptions import AuthenticationError, ConnectionError as RedisConnectionError
except Exception:  # pragma: no cover
    AuthenticationError = PermissionError  # type: ignore[assignment]
    RedisConnectionError = ConnectionError  # type: ignore[assignment]

OWNER = "falkordb-cognee-adapter"
SCHEMA_VERSION = "1"


def _connect(args: argparse.Namespace) -> FalkorDB:
    password = args.password if args.password is not None else os.getenv("FALKOR_PASSWORD", "")
    return FalkorDB(
        host=args.host or os.getenv("FALKOR_HOST", "127.0.0.1"),
        port=args.port or int(os.getenv("FALKOR_PORT", "6379")),
        password=password or None,
        socket_timeout=2,
        socket_connect_timeout=2,
    )


def _parse_graphs(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _has_owner_marker(db: FalkorDB, graph_name: str) -> bool:
    graph = db.select_graph(graph_name)
    result = graph.query(
        "MATCH (m:DatasetMeta {owner: $owner}) RETURN count(m)", {"owner": OWNER}
    )
    return int(result.result_set[0][0]) > 0


def _create_roster(db: FalkorDB, *, dry_run: bool) -> None:
    for graph_name in sorted(CANON_DATASETS):
        if dry_run:
            print(f"DRY-RUN create marker in {graph_name}")
            continue
        db.select_graph(graph_name).query(
            """
            MERGE (m:DatasetMeta {owner: $owner})
            SET m.schema_version = $schema_version,
                m.dataset = $dataset
            """,
            {"owner": OWNER, "schema_version": SCHEMA_VERSION, "dataset": graph_name},
        )
        print(f"created/verified {graph_name}")


def _drop_graphs(
    db: FalkorDB,
    graph_names: list[str],
    *,
    confirm_drop_fraud: bool,
    yes: bool,
    dry_run: bool,
) -> int:
    if not graph_names:
        return 0

    allowed: list[str] = []
    rejected: list[str] = []
    for graph_name in graph_names:
        marker = _has_owner_marker(db, graph_name)
        fraud_escape = confirm_drop_fraud and yes
        if marker or fraud_escape:
            allowed.append(graph_name)
        else:
            rejected.append(graph_name)

    if rejected:
        print(
            "unsafe drop request rejected; missing DatasetMeta marker and fraud confirmation: "
            + ",".join(rejected),
            file=sys.stderr,
        )
        return 1

    for graph_name in allowed:
        if dry_run:
            print(f"DRY-RUN delete {graph_name}")
            continue
        db.select_graph(graph_name).delete()
        print(f"deleted {graph_name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--create-roster", action="store_true")
    parser.add_argument("--drop-graphs")
    parser.add_argument("--confirm-drop-fraud", action="store_true")
    parser.add_argument("--yes", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dry_run = args.dry_run or (not args.create_roster and not args.drop_graphs)
    try:
        db = _connect(args)
        db.list_graphs()
        if args.create_roster:
            _create_roster(db, dry_run=dry_run)
        return _drop_graphs(
            db,
            _parse_graphs(args.drop_graphs),
            confirm_drop_fraud=args.confirm_drop_fraud,
            yes=args.yes,
            dry_run=dry_run,
        )
    except AuthenticationError as exc:
        print(f"falkordb permission error: {exc}", file=sys.stderr)
        return 3
    except (RedisConnectionError, ConnectionError, OSError) as exc:
        print(f"falkordb unreachable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
