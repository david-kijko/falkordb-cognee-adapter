"""Shared pytest configuration for the FalkorDB Cognee adapter tests."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from falkordb import FalkorDB

if TYPE_CHECKING:
    from fca.adapter import FalkorCogneeAdapter


@pytest.fixture
def falkordb_test() -> Iterator["FalkorCogneeAdapter"]:
    """Yield an adapter bound to a fresh graph on the docker FalkorDB test instance."""
    try:
        db = FalkorDB(host="127.0.0.1", port=6380, socket_timeout=1, socket_connect_timeout=1)
        db.list_graphs()
    except Exception as exc:  # pragma: no cover - depends on local docker state
        pytest.skip(
            "FalkorDB test instance is not running on 127.0.0.1:6380; "
            "start it with `docker compose -f docker-compose.test.yml up -d` "
            f"({exc!r})"
        )

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
