#!/usr/bin/env python3
"""Freeze Cognee 1.0.3 graph/vector abstract method signatures for upgrade tests."""

from __future__ import annotations

import inspect
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cognee
from cognee.infrastructure.databases.graph.graph_db_interface import GraphDBInterface
from cognee.infrastructure.databases.vector.vector_db_interface import VectorDBInterface

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "cognee_1_0_3_contract.json"


def _version() -> str:
    version = getattr(cognee, "__version__", None)
    if version:
        return str(version)
    try:
        from importlib.metadata import version as package_version

        return package_version("cognee")
    except Exception:  # pragma: no cover - defensive fallback for unusual installs
        return "unknown"


def _abstract_methods(interface: type[Any]) -> list[dict[str, str]]:
    names = sorted(getattr(interface, "__abstractmethods__", frozenset()))
    return [
        {"name": name, "signature": str(inspect.signature(getattr(interface, name)))}
        for name in names
    ]


def _existing_frozen_at() -> str | None:
    if not OUT.exists():
        return None
    try:
        existing = json.loads(OUT.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    value = existing.get("frozen_at")
    return value if isinstance(value, str) else None


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frozen_at = _existing_frozen_at() or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload = {
        "frozen_at": frozen_at,
        "cognee_version": _version(),
        "python_version": platform.python_version(),
        "graph_db_interface": {
            "module": GraphDBInterface.__module__,
            "abstract_methods": _abstract_methods(GraphDBInterface),
        },
        "vector_db_interface": {
            "module": VectorDBInterface.__module__,
            "abstract_methods": _abstract_methods(VectorDBInterface),
        },
    }
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print(
        "graph_methods="
        f"{len(payload['graph_db_interface']['abstract_methods'])} "
        "vector_methods="
        f"{len(payload['vector_db_interface']['abstract_methods'])}"
    )


if __name__ == "__main__":
    main()
