"""Dataset router for graph-per-dataset FalkorCogneeAdapter instances."""

from __future__ import annotations

import time
from typing import Any

from falkordb import FalkorDB

from fca.adapter import FalkorCogneeAdapter
from fca.isolation import DatasetIsolationStrategy, GraphPerDataset
from fca.roles import Role
from fca.telemetry import NullSink, TelemetrySink


class DatasetRouter:
    """
    Maps logical dataset name -> FalkorCogneeAdapter instance bound to that
    graph_name. Holds the FalkorDB connection. Caches adapters per dataset.
    """

    def __init__(
        self,
        host: str,
        port: int,
        password: str,
        role: Role,
        isolation: DatasetIsolationStrategy | None = None,
        telemetry: TelemetrySink | None = None,
    ):
        self.host = host
        self.port = port
        self.password = password
        self.role = role
        self._iso = isolation or GraphPerDataset()
        self._telemetry = telemetry or NullSink()
        self._db = FalkorDB(host=host, port=port, password=password or None)
        self._cache: dict[str, FalkorCogneeAdapter] = {}

    def for_dataset(self, dataset: str) -> FalkorCogneeAdapter:
        graph_name = self._iso.graph_name_for(dataset)
        if dataset not in self._cache:
            self._cache[dataset] = FalkorCogneeAdapter(
                self.host,
                self.port,
                self.password,
                graph_name,
                self.role,
                isolation=self._iso,
                telemetry=self._telemetry,
            )
        return self._cache[dataset]

    async def delete_dataset(self, dataset: str) -> None:
        # TODO(slice-2): wire role guard
        self._emit("delete_dataset", dataset=dataset)
        start = time.perf_counter()
        self._iso.delete(self._db, dataset)
        self._cache.pop(dataset, None)
        self._emit("delete_dataset", dataset=dataset, latency_ms=(time.perf_counter() - start) * 1000, rows_out=0)

    def _emit(self, op: str, *, dataset: str, latency_ms: float | None = None, rows_out: int | None = None) -> None:
        event: dict[str, Any] = {
            "op": op,
            "dataset": dataset,
            "role": self.role.value,
            "latency_ms": latency_ms,
            "rows_in": 1,
            "rows_out": rows_out,
            "retries": 0,
            "failure_class": None,
            "schema_version": "1",
            "ts": time.time(),
        }
        self._telemetry.emit(event)
