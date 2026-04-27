from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

from cognee.infrastructure.databases.graph.graph_db_interface import GraphDBInterface
from cognee.infrastructure.databases.vector.vector_db_interface import VectorDBInterface

from fca.exceptions import CogneeContractError


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "cognee_1_0_3_contract.json"


def _abstract_methods(interface: type[Any]) -> list[dict[str, str]]:
    return [
        {"name": name, "signature": str(inspect.signature(getattr(interface, name)))}
        for name in sorted(interface.__abstractmethods__)
    ]


def _assert_same(section: str, expected: list[dict[str, str]], actual: list[dict[str, str]]) -> None:
    if expected != actual:
        raise CogneeContractError(
            f"Cognee {section} abstract method drift: expected={expected!r} actual={actual!r}"
        )


def test_installed_cognee_matches_frozen_fixture():
    """SP6: fail the upgrade gate if installed Cognee drifts from the frozen fixture."""
    frozen = json.loads(FIXTURE.read_text(encoding="utf-8"))
    _assert_same(
        "graph",
        frozen["graph_db_interface"]["abstract_methods"],
        _abstract_methods(GraphDBInterface),
    )
    _assert_same(
        "vector",
        frozen["vector_db_interface"]["abstract_methods"],
        _abstract_methods(VectorDBInterface),
    )
