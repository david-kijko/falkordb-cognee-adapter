"""FalkorDB driver session and typed error translation."""

from __future__ import annotations

import socket
from typing import Any

from falkordb import FalkorDB

from fca.exceptions import (
    FalkorAdapterError,
    FalkorConnectionError,
    FalkorQueryError,
    FalkorTimeoutError,
)

try:  # pragma: no cover - import shape depends on redis package version
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import TimeoutError as RedisTimeoutError
except Exception:  # pragma: no cover
    RedisConnectionError = ConnectionError  # type: ignore[assignment]
    RedisTimeoutError = TimeoutError  # type: ignore[assignment]


_CONNECTION_ERRORS = (ConnectionError, ConnectionRefusedError, OSError, RedisConnectionError)
_TIMEOUT_ERRORS = (TimeoutError, socket.timeout, RedisTimeoutError)


class FalkorSession:
    """Thin wrapper around ``FalkorDB().select_graph()`` with typed failures."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        password: str,
        graph_name: str,
        socket_timeout: float,
        connection_timeout: float,
    ) -> None:
        self.host = host
        self.port = port
        self.password = password or None
        self.graph_name = graph_name
        self.socket_timeout = socket_timeout
        self.connection_timeout = connection_timeout
        self._db: FalkorDB | None = None

    @property
    def db(self) -> FalkorDB:
        if self._db is None:
            try:
                self._db = FalkorDB(
                    host=self.host,
                    port=self.port,
                    password=self.password,
                    socket_timeout=self.socket_timeout,
                    socket_connect_timeout=self.connection_timeout,
                )
            except Exception as exc:  # noqa: BLE001 - must translate all driver failures
                raise self.translate(exc) from exc
        return self._db

    @property
    def graph(self):
        try:
            return self.db.select_graph(self.graph_name)
        except Exception as exc:  # noqa: BLE001
            raise self.translate(exc) from exc

    def execute(self, cypher: str, params: dict[str, Any] | None = None, *, read_only: bool = False):
        try:
            graph = self.graph
            runner = graph.ro_query if read_only else graph.query
            return runner(cypher, params or {})
        except Exception as exc:  # noqa: BLE001
            raise self.translate(exc) from exc

    def delete_graph(self) -> None:
        try:
            self.graph.delete()
        except Exception as exc:  # noqa: BLE001
            raise self.translate(exc) from exc

    def list_graphs(self) -> list[str]:
        try:
            return list(self.db.list_graphs())
        except Exception as exc:  # noqa: BLE001
            raise self.translate(exc) from exc

    def list_indices(self):
        try:
            return self.graph.list_indices()
        except Exception as exc:  # noqa: BLE001
            raise self.translate(exc) from exc

    def create_node_vector_index(
        self, label: str, property_name: str, *, dim: int, similarity_function: str
    ):
        try:
            return self.graph.create_node_vector_index(
                label, property_name, dim=dim, similarity_function=similarity_function
            )
        except Exception as exc:  # noqa: BLE001
            raise self.translate(exc) from exc

    def drop_node_vector_index(self, label: str, property_name: str):
        try:
            return self.graph.drop_node_vector_index(label, property_name)
        except Exception as exc:  # noqa: BLE001
            raise self.translate(exc) from exc

    @staticmethod
    def translate(exc: Exception) -> FalkorAdapterError:
        if isinstance(exc, FalkorAdapterError):
            return exc
        if isinstance(exc, _TIMEOUT_ERRORS):
            return FalkorTimeoutError(str(exc))
        if isinstance(exc, _CONNECTION_ERRORS):
            return FalkorConnectionError(str(exc))
        return FalkorQueryError(str(exc))
