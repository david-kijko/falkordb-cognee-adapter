"""Telemetry hook contracts for adapter operations.

Event schema (``schema_version == "1"``): ``op`` (str), ``dataset`` (str),
``role`` (str), ``latency_ms`` (float | None), ``rows_in`` (int | None),
``rows_out`` (int | None), ``retries`` (int), ``failure_class`` (str | None),
``schema_version`` (str), and ``ts`` (float from ``time.time()``).

Failure class taxonomy:

- ``connection``: ``FalkorConnectionError`` from FalkorDB/Redis connection setup
  or connection loss; all adapter operations can produce it when the driver is
  unavailable.
- ``query``: ``FalkorQueryError`` from rejected FalkorDB query execution or
  unsupported adapter payloads; graph and vector operations that issue Cypher can
  produce it.
- ``schema``: ``FalkorSchemaError`` from unsafe labels, relationship types,
  properties, vector collection names, or invalid graph traversal parameters;
  write operations and vector/search helpers that build Cypher can produce it.
- ``timeout``: ``FalkorTimeoutError`` from socket/connect timeouts; all driver
  backed operations can produce it.
- ``embedding``: ``FalkorEmbeddingError`` from missing vector collections,
  embedding/vector dimension failures, or embedding-service failures; vector
  create/search/embed operations can produce it.
- ``read_authority``: ``ReadAuthorityError`` from read operations whose role may
  not read the adapter dataset.
- ``write_authority``: ``WriteAuthorityError`` from write/delete operations whose
  role may not write the adapter dataset.
- ``query_guard``: ``QueryGuardError`` from read-mode Cypher containing write or
  index-create tokens; produced by ``query`` before driver execution.
- ``cognee_contract_drift``: ``CogneeContractError`` from contract upgrade checks
  when installed Cognee signatures drift from the frozen fixture.

Operation families: read graph ops (``query``, ``is_empty``, ``get_*``,
``has_*``) can produce read authority, query guard (``query`` only), schema,
connection, timeout, and query failures. Write graph ops (``add_*``,
``delete_*``, ``prune``) can produce write authority, schema, connection,
timeout, and query failures. Vector ops (``create_collection``,
``create_data_points``, ``retrieve``, ``search``, ``batch_search``,
``delete_data_points``, ``embed_data``) add the ``embedding`` class when vector
collection or embedding invariants fail. Upgrade contract tests, not normal
runtime traffic, produce ``cognee_contract_drift``.

``StdlibSink`` writes one structured JSON line per ``emit`` call to stderr or an
append-only file. It has no OpenTelemetry dependency; OTel remains deferred to
v0.2 behind the ``TelemetrySink`` protocol.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Protocol, TextIO, runtime_checkable


@runtime_checkable
class TelemetrySink(Protocol):
    def emit(self, event: dict[str, Any]) -> None: ...


class NullSink:
    """No-op sink. Default if caller doesn't pass one."""

    def emit(self, event: dict[str, Any]) -> None:
        pass


class StdlibSink:
    """Production-grade JSON-lines telemetry sink.

    Writes structured events to ``stream`` (default ``sys.stderr``) or appends to
    ``path`` when provided. Each ``emit`` call writes exactly one JSON line,
    flushes it, and optionally fsyncs for crash safety.
    """

    def __init__(
        self,
        stream: TextIO | None = None,
        path: Path | str | None = None,
        fsync_each: bool = False,
        schema_version: str = "1",
    ) -> None:
        if stream is not None and path is not None:
            raise ValueError("StdlibSink accepts either stream or path, not both")
        self._owns_stream = path is not None
        self._stream = open(Path(path), "a", encoding="utf-8") if path is not None else stream or sys.stderr
        self._fsync_each = fsync_each
        self._schema_version = schema_version

    def emit(self, event: dict[str, Any]) -> None:
        payload = dict(event)
        payload.setdefault("schema_version", self._schema_version)
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        self._stream.write(f"{line}\n")
        self._stream.flush()
        if self._fsync_each:
            fileno = self._stream.fileno()
            os.fsync(fileno)

    def close(self) -> None:
        if self._owns_stream:
            self._stream.close()

    def __enter__(self) -> StdlibSink:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
