from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from fca.adapter import FalkorCogneeAdapter
from fca.exceptions import (
    CogneeContractError,
    FalkorConnectionError,
    FalkorEmbeddingError,
    FalkorQueryError,
    FalkorSchemaError,
    FalkorTimeoutError,
    QueryGuardError,
    ReadAuthorityError,
    WriteAuthorityError,
)
from fca.roles import Role


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)


def _adapter(*, graph_name: str | None = None, role: Role = Role.ARCHIE) -> tuple[FalkorCogneeAdapter, _RecordingSink]:
    sink = _RecordingSink()
    adapter = FalkorCogneeAdapter(
        host="127.0.0.1",
        port=6380,
        password="",
        graph_name=graph_name or f"session_failure_class_{uuid4().hex}",
        role=role,
        telemetry=sink,
        socket_timeout=0.1,
        connection_timeout=0.1,
    )
    return adapter, sink


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception_type",
    [
        FalkorConnectionError,
        FalkorQueryError,
        FalkorSchemaError,
        FalkorTimeoutError,
        FalkorEmbeddingError,
        CogneeContractError,
    ],
)
async def test_driver_and_adapter_typed_exceptions_emit_declared_failure_class(monkeypatch, exception_type) -> None:
    adapter, sink = _adapter()
    monkeypatch.setattr(adapter, "_execute", lambda *args, **kwargs: (_ for _ in ()).throw(exception_type("forced")))

    with pytest.raises(exception_type):
        await adapter.add_node("a", {"type": "Node"})

    assert len(sink.events) == 1
    assert sink.events[0]["failure_class"] == exception_type.failure_class


@pytest.mark.asyncio
async def test_read_authority_error_emits_declared_failure_class() -> None:
    adapter, sink = _adapter(graph_name="ingestion_metadata", role=Role.ARCHIE)

    with pytest.raises(ReadAuthorityError):
        await adapter.query("MATCH (n) RETURN n", {})

    assert len(sink.events) == 1
    assert sink.events[0]["failure_class"] == ReadAuthorityError.failure_class


@pytest.mark.asyncio
async def test_write_authority_error_emits_declared_failure_class() -> None:
    adapter, sink = _adapter(graph_name="canon", role=Role.VALIDATOR)

    with pytest.raises(WriteAuthorityError):
        await adapter.add_node("a", {"type": "Node"})

    assert len(sink.events) == 1
    assert sink.events[0]["failure_class"] == WriteAuthorityError.failure_class


@pytest.mark.asyncio
async def test_query_guard_error_emits_declared_failure_class() -> None:
    adapter, sink = _adapter(graph_name="canon", role=Role.ARCHIE)

    with pytest.raises(QueryGuardError):
        await adapter.query("CREATE (n) RETURN n", {})

    assert len(sink.events) == 1
    assert sink.events[0]["failure_class"] == QueryGuardError.failure_class
