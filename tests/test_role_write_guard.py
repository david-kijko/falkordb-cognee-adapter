from __future__ import annotations

import pytest

from fca.adapter import FalkorCogneeAdapter
from fca.exceptions import WriteAuthorityError
from fca.roles import Role


@pytest.mark.parametrize(
    ("role", "dataset", "expect"),
    [
        (Role.INGESTOR, "canon", True),
        (Role.INGESTOR, "exemplars", True),
        (Role.INGESTOR, "ingestion_metadata", True),
        (Role.INGESTOR, "lessons", False),
        (Role.INGESTOR, "session_abc", False),
        (Role.VALIDATOR, "lessons", True),
        (Role.VALIDATOR, "canon_errata", True),
        (Role.VALIDATOR, "canon", False),
        (Role.ARCHIE, "quarantine", True),
        (Role.ARCHIE, "session_uuid-xyz", True),
        (Role.ARCHIE, "investigation_42", True),
        (Role.ARCHIE, "canon", False),
        (Role.ARCHIE, "lessons", False),
    ],
)
def test_can_write_matrix(role, dataset, expect):
    from fca.roles import can_write

    assert can_write(role, dataset) is expect


@pytest.mark.asyncio
async def test_archie_cannot_write_canon_via_adapter(falkordb_test):
    """End-to-end: archie role + add_node to canon -> WriteAuthorityError raised."""
    adapter = FalkorCogneeAdapter(
        host=falkordb_test.host,
        port=falkordb_test.port,
        password=falkordb_test.password,
        graph_name="canon",
        role=Role.ARCHIE,
        socket_timeout=2,
        connection_timeout=1,
    )

    with pytest.raises(WriteAuthorityError):
        await adapter.add_node("forbidden", {"type": "FORBIDDEN"})
