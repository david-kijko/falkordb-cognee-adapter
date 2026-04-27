"""Telemetry hook contracts for adapter operations.

Event schema (``schema_version == "1"``): ``op`` (str), ``dataset`` (str),
``role`` (str), ``latency_ms`` (float | None), ``rows_in`` (int | None),
``rows_out`` (int | None), ``retries`` (int), ``failure_class`` (str | None),
``schema_version`` (str), and ``ts`` (float from ``time.time()``).

Slice 7 fills in ``StdlibSink`` to write structured JSON to stderr/file.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TelemetrySink(Protocol):
    def emit(self, event: dict[str, Any]) -> None: ...


class NullSink:
    """No-op sink. Default if caller doesn't pass one."""

    def emit(self, event: dict[str, Any]) -> None:
        pass


# Slice 7 fills: StdlibSink (writes structured JSON to stderr/file)
