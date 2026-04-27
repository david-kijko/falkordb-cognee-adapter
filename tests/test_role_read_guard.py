from __future__ import annotations

import pytest

from fca.adapter import FalkorCogneeAdapter
from fca.exceptions import ReadAuthorityError
from fca.roles import Role


@pytest.mark.parametrize(
    ("role", "dataset", "expect"),
    [
        (Role.INGESTOR, "canon", True),
        (Role.INGESTOR, "exemplars", True),
        (Role.INGESTOR, "ingestion_metadata", True),
        (Role.INGESTOR, "lessons", False),
        (Role.INGESTOR, "quarantine", False),
        (Role.INGESTOR, "session_abc", True),
        (Role.VALIDATOR, "canon", True),
        (Role.VALIDATOR, "exemplars", True),
        (Role.VALIDATOR, "lessons", True),
        (Role.VALIDATOR, "canon_errata", True),
        (Role.VALIDATOR, "quarantine", True),
        (Role.VALIDATOR, "ingestion_metadata", True),
        (Role.VALIDATOR, "investigation_42", True),
        (Role.ARCHIE, "canon", True),
        (Role.ARCHIE, "exemplars", True),
        (Role.ARCHIE, "lessons", True),
        (Role.ARCHIE, "canon_errata", True),
        (Role.ARCHIE, "quarantine", True),
        (Role.ARCHIE, "ingestion_metadata", False),
        (Role.ARCHIE, "session_uuid-xyz", True),
        (Role.ARCHIE, "randomname", False),
    ],
)
def test_can_read_matrix(role, dataset, expect):
    from fca.roles import can_read

    assert can_read(role, dataset) is expect


@pytest.mark.asyncio
async def test_ingestor_cannot_read_lessons_via_adapter(falkordb_test):
    """End-to-end: ingestor role + read from lessons -> ReadAuthorityError raised."""
    adapter = FalkorCogneeAdapter(
        host=falkordb_test.host,
        port=falkordb_test.port,
        password=falkordb_test.password,
        graph_name="lessons",
        role=Role.INGESTOR,
        socket_timeout=2,
        connection_timeout=1,
    )

    with pytest.raises(ReadAuthorityError):
        await adapter.get_graph_metrics()
