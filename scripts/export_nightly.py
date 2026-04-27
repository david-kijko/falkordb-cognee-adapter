#!/usr/bin/env python3
"""Export selected FalkorDB graphs to compressed Cypher archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from falkordb import FalkorDB

DEFAULT_DATASETS = ("canon", "exemplars", "lessons", "canon_errata")
SKIP_EXACT = {"quarantine", "ingestion_metadata"}
SKIP_PREFIXES = ("session_", "investigation_")
EXPORTER_VERSION = "0.1.0"
SCHEMA_VERSION = "1"
RETAINED_ARCHIVES = 24 + 30 + 52
EXPORT_ID_PROP = "__fca_export_id"


def _connect(args: argparse.Namespace) -> FalkorDB:
    password = args.password if args.password is not None else os.getenv("FALKOR_PASSWORD", "")
    return FalkorDB(
        host=args.host or os.getenv("FALKOR_HOST", "127.0.0.1"),
        port=args.port or int(os.getenv("FALKOR_PORT", "6379")),
        password=password or None,
        socket_timeout=5,
        socket_connect_timeout=2,
    )


def _datasets(raw: str | None) -> list[str]:
    if raw is None:
        return list(DEFAULT_DATASETS)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _should_skip(graph: str) -> bool:
    return graph in SKIP_EXACT or graph.startswith(SKIP_PREFIXES)


def _quote_name(value: str) -> str:
    return "`" + value.replace("`", "``") + "`"


def _cypher_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | Decimal):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_cypher_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return _cypher_props(value)
    return json.dumps(str(value))


def _cypher_props(props: dict[str, Any]) -> str:
    return "{" + ", ".join(
        f"{_quote_name(str(key))}: {_cypher_value(value)}" for key, value in props.items()
    ) + "}"


def _node_statement(node_id: int, labels: list[str], props: dict[str, Any]) -> str:
    merged = {EXPORT_ID_PROP: node_id, **dict(props)}
    label_text = "".join(f":{_quote_name(label)}" for label in labels)
    return f"CREATE ({label_text} {_cypher_props(merged)});"


def _edge_statement(start_id: int, end_id: int, rel_type: str, props: dict[str, Any]) -> str:
    return (
        f"MATCH (a {{{_quote_name(EXPORT_ID_PROP)}: {start_id}}}), "
        f"(b {{{_quote_name(EXPORT_ID_PROP)}: {end_id}}}) "
        f"CREATE (a)-[:{_quote_name(rel_type)} {_cypher_props(dict(props))}]->(b);"
    )


def _write_cypher(db: FalkorDB, graph_name: str, out: Path) -> tuple[int, int]:
    graph = db.select_graph(graph_name)
    node_rows = graph.query(
        "MATCH (n) RETURN id(n), labels(n), properties(n) ORDER BY id(n)"
    ).result_set
    edge_rows = graph.query(
        "MATCH (a)-[r]->(b) RETURN id(a), id(b), type(r), properties(r) ORDER BY id(r)"
    ).result_set
    with out.open("w", encoding="utf-8") as handle:
        for node_id, labels, props in node_rows:
            handle.write(_node_statement(int(node_id), list(labels), dict(props)) + "\n")
        for start_id, end_id, rel_type, props in edge_rows:
            handle.write(
                _edge_statement(int(start_id), int(end_id), str(rel_type), dict(props)) + "\n"
            )
        if node_rows:
            handle.write(f"MATCH (n) REMOVE n.{_quote_name(EXPORT_ID_PROP)};\n")
    return len(node_rows), len(edge_rows)


def _compress_zstd(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["zstd", "-q", "-f", str(source), "-o", str(target)], check=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_path(archive: Path) -> Path:
    return archive.with_suffix(archive.suffix + ".manifest.json")


def _enforce_retention_and_budget(graph_root: Path, budget_bytes: int) -> bool:
    archives = sorted(graph_root.glob("**/*.cypher.zst"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old_archive in archives[RETAINED_ARCHIVES:]:
        old_manifest = _manifest_path(old_archive)
        old_archive.unlink(missing_ok=True)
        old_manifest.unlink(missing_ok=True)
    retained = archives[:RETAINED_ARCHIVES]
    projected = sum(path.stat().st_size for path in retained if path.exists())
    if projected > budget_bytes:
        print(
            f"budget exceeded for {graph_root.name}: {projected} > {budget_bytes}",
            file=sys.stderr,
        )
        return False
    return True


def export_graph(db: FalkorDB, graph_name: str, output_root: Path, budget_bytes: int) -> int:
    if _should_skip(graph_name):
        print(f"skipping non-exportable graph {graph_name}")
        return 0
    now = datetime.now(timezone.utc).replace(microsecond=0)
    archive = output_root / graph_name / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
    archive = archive / f"{now:%H}.cypher.zst"
    with tempfile.TemporaryDirectory() as temp_dir:
        cypher_path = Path(temp_dir) / f"{graph_name}.cypher"
        node_count, edge_count = _write_cypher(db, graph_name, cypher_path)
        _compress_zstd(cypher_path, archive)
    manifest = {
        "graph": graph_name,
        "snapshot_at": now.isoformat(),
        "node_count": node_count,
        "edge_count": edge_count,
        "sha256": _sha256(archive),
        "schema_version": SCHEMA_VERSION,
        "exporter_version": EXPORTER_VERSION,
    }
    _manifest_path(archive).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"exported {graph_name} nodes={node_count} edges={edge_count} archive={archive}")
    return 0 if _enforce_retention_and_budget(output_root / graph_name, budget_bytes) else 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--datasets", default=None)
    parser.add_argument("--output-root", type=Path, default=Path("./backups"))
    parser.add_argument("--budget-bytes", type=int, default=21474836480)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = _connect(args)
    exit_code = 0
    for graph_name in _datasets(args.datasets):
        exit_code = max(exit_code, export_graph(db, graph_name, args.output_root, args.budget_bytes))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
