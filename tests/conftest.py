"""Shared pytest configuration for the FalkorDB Cognee adapter tests."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from falkordb import FalkorDB

if TYPE_CHECKING:
    from fca.adapter import FalkorCogneeAdapter


def pytest_addoption(parser):
    parser.addoption(
        "--require-fixtures",
        action="store_true",
        default=False,
        help="Fail (instead of skip) when external fixtures unavailable.",
    )


@pytest.fixture
def falkordb_test(request) -> Iterator["FalkorCogneeAdapter"]:
    """Yield an adapter bound to a fresh graph on the docker FalkorDB test instance."""
    try:
        db = FalkorDB(host="127.0.0.1", port=6380, socket_timeout=1, socket_connect_timeout=1)
        db.list_graphs()
    except Exception as exc:  # pragma: no cover - depends on local docker state
        message = (
            "FalkorDB :6380 not reachable; start with "
            "`docker compose -f docker-compose.test.yml up -d` "
            f"({exc!r})"
        )
        if request.config.getoption("--require-fixtures"):
            pytest.fail(f"FalkorDB :6380 not reachable; required by --require-fixtures. {exc!r}")
        pytest.skip(message)

    from fca.adapter import FalkorCogneeAdapter
    from fca.roles import Role

    graph_name = f"session_test_{uuid4().hex}"
    adapter = FalkorCogneeAdapter(
        host="127.0.0.1",
        port=6380,
        password="",
        graph_name=graph_name,
        role=Role.ARCHIE,
        socket_timeout=2,
        connection_timeout=1,
    )
    try:
        yield adapter
    finally:
        try:
            FalkorDB(host="127.0.0.1", port=6380).select_graph(graph_name).delete()
        except Exception:
            pass
