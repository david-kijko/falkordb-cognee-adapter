from __future__ import annotations

import pytest

from fca.exceptions import FalkorConnectionError, FalkorQueryError
from fca.roles import Role
from fca.telemetry import NullSink


class RecordingSink(NullSink):
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, event: dict) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_connection_error_surfaces_as_typed_exception(monkeypatch):
    """SP4: driver failure produces FalkorConnectionError, NEVER empty success."""
    import fca._falkor_session as session_mod
    from fca.adapter import FalkorCogneeAdapter

    class BrokenFalkorDB:
        def __init__(self, *args, **kwargs):
            raise ConnectionRefusedError("boom")

    monkeypatch.setattr(session_mod, "FalkorDB", BrokenFalkorDB)
    adapter = FalkorCogneeAdapter("127.0.0.1", 6399, "", "broken", Role.ARCHIE)

    with pytest.raises(FalkorConnectionError):
        await adapter.add_node("n1", {"type": "TEST_NODE"})


@pytest.mark.asyncio
async def test_query_error_surfaces_as_typed_exception(falkordb_test):
    """SP4: malformed Cypher produces FalkorQueryError, NEVER empty success."""
    sink = RecordingSink()
    falkordb_test.telemetry = sink

    with pytest.raises(FalkorQueryError):
        await falkordb_test.query("INVALID SYNTAX")

    assert any(event.get("failure_class") == "query" for event in sink.events)
