"""Cognee 1.0.3 hybrid graph/vector adapter for FalkorDB."""

from __future__ import annotations

import time
from typing import Any, Optional
from uuid import NAMESPACE_URL, UUID, uuid5
from cognee.infrastructure.databases.graph.graph_db_interface import GraphDBInterface
from cognee.infrastructure.databases.vector.models.ScoredResult import ScoredResult
from cognee.infrastructure.databases.vector.vector_db_interface import VectorDBInterface

from fca import _cypher_builders as cy
from fca._falkor_session import FalkorSession
from fca._vector_index import VectorIndexManager, collection_parts, dimension_from_schema, vector_query
from fca.exceptions import FalkorAdapterError, FalkorQueryError
from fca.isolation import DatasetIsolationStrategy, GraphPerDataset
from fca.roles import Role
from fca.telemetry import NullSink, TelemetrySink

class ResultList(list):
    """Plain list with a ``result_set`` alias for Cognee/upstream compatibility."""
    @property
    def result_set(self):
        return self


class FalkorCogneeAdapter(GraphDBInterface, VectorDBInterface):
    """
    Cognee 1.0.3 hybrid adapter for FalkorDB. Bound to ONE graph_name.
    Multi-graph routing happens in DatasetRouter (router.py).
    """
    def __init__(
        self,
        host: str,
        port: int,
        password: str,
        graph_name: str,
        role: Role,
        isolation: DatasetIsolationStrategy | None = None,
        telemetry: TelemetrySink | None = None,
        socket_timeout: float = 5.0,
        connection_timeout: float = 3.0,
    ):
        self.host = host
        self.port = port
        self.password = password
        self.graph_name = graph_name
        self.role = role
        self.isolation = isolation or GraphPerDataset()
        self.telemetry = telemetry or NullSink()
        self._session = FalkorSession(
            host=host,
            port=port,
            password=password,
            graph_name=graph_name,
            socket_timeout=socket_timeout,
            connection_timeout=connection_timeout,
        )
        self._vectors = VectorIndexManager(self._session)
    def _event(
        self,
        op: str,
        *,
        latency_ms: float | None = None,
        rows_in: int | None = None,
        rows_out: int | None = None,
        failure_class: str | None = None,
    ) -> dict[str, Any]:
        return {
            "op": op,
            "dataset": self.graph_name,
            "role": self.role.value,
            "latency_ms": latency_ms,
            "rows_in": rows_in,
            "rows_out": rows_out,
            "retries": 0,
            "failure_class": failure_class,
            "schema_version": "1",
            "ts": time.time(),
        }

    def _emit_event(self, op: str, **fields: Any) -> None:
        self.telemetry.emit(self._event(op, **fields))

    def _run_cypher(
        self,
        op: str,
        statement: str,
        params: dict[str, Any] | None = None,
        *,
        rows_in: int | None = None,
        read_only: bool = False,
    ) -> ResultList:
        self._emit_event(op, rows_in=rows_in)
        start = time.perf_counter()
        try:
            raw = self._session.execute(statement, params or {}, read_only=read_only)
            rows = ResultList(raw.result_set or [])
        except FalkorAdapterError as exc:
            self._emit_event(
                op,
                latency_ms=(time.perf_counter() - start) * 1000,
                rows_in=rows_in,
                failure_class=exc.failure_class,
            )
            raise
        self._emit_event(
            op,
            latency_ms=(time.perf_counter() - start) * 1000,
            rows_in=rows_in,
            rows_out=len(rows),
        )
        return rows

    async def query(self, query: str, params: dict | None = None) -> list[Any]:
        return self._run_cypher("query", query, params or {})

    async def is_empty(self) -> bool:
        self._emit_event("is_empty")
        start = time.perf_counter()
        try:
            if self.graph_name not in self._session.list_graphs():
                empty = True
            else:
                rows = self._session.execute(*cy.is_empty(), read_only=True).result_set or []
                empty = bool(rows[0][0]) if rows else True
        except FalkorAdapterError as exc:
            self._emit_event("is_empty", latency_ms=(time.perf_counter() - start) * 1000, failure_class=exc.failure_class)
            raise
        self._emit_event("is_empty", latency_ms=(time.perf_counter() - start) * 1000, rows_out=1)
        return empty

    async def add_node(self, node: Any, properties: Optional[dict[str, Any]] = None) -> None:
        node_id, props = self._node_payload(node, properties)
        self._run_cypher("add_node", *cy.add_node(node_id, props), rows_in=1)

    async def add_nodes(self, nodes: list[Any]) -> None:
        if not nodes:
            self._emit_event("add_nodes", rows_in=0)
            self._emit_event("add_nodes", latency_ms=0.0, rows_in=0, rows_out=0)
            return
        normalized = [self._node_payload(node, None) for node in nodes]
        for statement, params in cy.grouped_add_nodes(normalized):
            self._run_cypher("add_nodes", statement, params, rows_in=len(params["items"]))

    async def delete_node(self, node_id: str) -> None:
        self._run_cypher("delete_node", *cy.delete_node(node_id), rows_in=1)

    async def delete_nodes(self, node_ids: list[str]) -> None:
        self._run_cypher("delete_nodes", *cy.delete_nodes(node_ids), rows_in=len(node_ids))

    async def get_node(self, node_id: str) -> Optional[dict[str, Any]]:
        rows = self._run_cypher("get_node", *cy.get_node(node_id), read_only=True)
        return self._props(rows[0][0]) if rows else None

    async def get_nodes(self, node_ids: list[str]) -> list[dict[str, Any]]:
        rows = self._run_cypher("get_nodes", *cy.get_nodes(node_ids), rows_in=len(node_ids), read_only=True)
        return [self._props(row[0]) for row in rows]

    async def add_edge(
        self,
        source_id: str,
        target_id: str,
        relationship_name: str,
        properties: Optional[dict[str, Any]] = None,
    ) -> None:
        await self.add_edges([(source_id, target_id, relationship_name, properties or {})])
    async def add_edges(self, edges: list[tuple[str, str, str, dict[str, Any] | None]]) -> None:
        if not edges:
            self._emit_event("add_edges", rows_in=0)
            self._emit_event("add_edges", latency_ms=0.0, rows_in=0, rows_out=0)
            return
        for statement, params in cy.add_edges(edges):
            self._run_cypher("add_edges", statement, params, rows_in=len(params["items"]))

    async def delete_graph(self) -> None:
        self._emit_event("delete_graph")
        start = time.perf_counter()
        try:
            self._session.delete_graph()
        except FalkorAdapterError as exc:
            self._emit_event(
                "delete_graph",
                latency_ms=(time.perf_counter() - start) * 1000,
                failure_class=exc.failure_class,
            )
            raise
        self._emit_event("delete_graph", latency_ms=(time.perf_counter() - start) * 1000, rows_out=0)

    async def get_graph_data(self) -> tuple[list[tuple[str, dict[str, Any]]], list[tuple[str, str, str, dict[str, Any]]]]:
        node_rows = self._run_cypher("get_graph_data.nodes", *cy.graph_nodes(), read_only=True)
        edge_rows = self._run_cypher("get_graph_data.edges", *cy.graph_edges(), read_only=True)
        return ([self._node_tuple(row[0]) for row in node_rows], [self._edge_tuple(row) for row in edge_rows])

    async def get_graph_metrics(self, include_optional: bool = False) -> dict[str, Any]:
        rows = self._run_cypher("get_graph_metrics", *cy.graph_counts(), read_only=True)
        metrics = {"num_nodes": 0, "num_edges": 0}
        if rows:
            metrics = {"num_nodes": rows[0][0], "num_edges": rows[0][1]}
        if include_optional:
            label_rows = self._run_cypher("get_graph_metrics.labels", "MATCH (n) RETURN labels(n)", {}, read_only=True)
            metrics["labels"] = sorted({label for row in label_rows for label in row[0]})
        return metrics
    async def has_edge(self, source_id: str, target_id: str, relationship_name: str) -> bool:
        rows = self._run_cypher("has_edge", *cy.has_edge(source_id, target_id, relationship_name), read_only=True)
        return bool(rows[0][0]) if rows else False
    async def has_edges(self, edges: list[tuple[str, str, str, dict[str, Any]]]) -> list[tuple[str, str, str, dict[str, Any]]]:
        return [edge for edge in edges if await self.has_edge(edge[0], edge[1], edge[2])]
    async def get_edges(self, node_id: str) -> list[tuple[str, str, str, dict[str, Any]]]:
        rows = self._run_cypher("get_edges", *cy.get_edges(node_id), read_only=True)
        return [self._edge_tuple(row) for row in rows]
    async def get_neighbors(self, node_id: str) -> list[dict[str, Any]]:
        rows = self._run_cypher("get_neighbors", *cy.get_neighbors(node_id), read_only=True)
        return [self._props(row[0]) for row in rows]

    async def get_nodeset_subgraph(
        self, node_type: type[Any], node_name: list[str], node_name_filter_operator: str = "OR"
    ) -> tuple[list[tuple[int, dict]], list[tuple[int, int, str, dict]]]:
        rows = self._run_cypher(
            "get_nodeset_subgraph",
            *cy.nodeset_nodes(node_type, node_name, node_name_filter_operator),
            rows_in=len(node_name),
            read_only=True,
        )
        return ([(row[0], row[1]) for row in rows], [])
    async def get_connections(self, node_id: str | UUID) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
        rows = self._run_cypher("get_connections", *cy.get_connections(str(node_id)), read_only=True)
        return [(self._props(row[0]), self._props(row[1]), self._props(row[2])) for row in rows]

    async def get_neighborhood(
        self, node_ids: list[str], depth: int = 1, edge_types: Optional[list[str]] = None
    ) -> tuple[list[tuple[str, dict[str, Any]]], list[tuple[str, str, str, dict[str, Any]]]]:
        node_rows = self._run_cypher(
            "get_neighborhood.nodes",
            *cy.neighborhood_nodes(node_ids, depth, edge_types),
            rows_in=len(node_ids),
            read_only=True,
        )
        nodes = [self._node_tuple(row[0]) for row in node_rows]
        ids = [node_id for node_id, _ in nodes]
        edge_rows = self._run_cypher("get_neighborhood.edges", *cy.subgraph_edges(ids), rows_in=len(ids), read_only=True)
        return nodes, [self._edge_tuple(row) for row in edge_rows]

    async def get_filtered_graph_data(
        self, attribute_filters: list[dict[str, list[str | int]]]
    ) -> tuple[list[tuple[str, dict[str, Any]]], list[tuple[str, str, str, dict[str, Any]]]]:
        node_rows = self._run_cypher(
            "get_filtered_graph_data.nodes", *cy.filtered_nodes(attribute_filters), rows_in=len(attribute_filters), read_only=True
        )
        nodes = [self._node_tuple(row[0]) for row in node_rows]
        edge_rows = self._run_cypher("get_filtered_graph_data.edges", *cy.subgraph_edges([n[0] for n in nodes]), read_only=True)
        return nodes, [self._edge_tuple(row) for row in edge_rows]

    async def has_collection(self, collection_name: str) -> bool:
        self._emit_event("has_collection", rows_in=1)
        start = time.perf_counter()
        try:
            exists = self._vectors.has_collection(collection_name)
        except FalkorAdapterError as exc:
            self._emit_event("has_collection", latency_ms=(time.perf_counter() - start) * 1000, rows_in=1, failure_class=exc.failure_class)
            raise
        self._emit_event("has_collection", latency_ms=(time.perf_counter() - start) * 1000, rows_in=1, rows_out=int(exists))
        return exists

    async def create_collection(self, collection_name: str, payload_schema: Optional[Any] = None):
        dimension = dimension_from_schema(payload_schema)
        self._vectors.ensure_index(collection_name, dimension)
        self._run_cypher("create_collection", "MERGE (c:FCA_COLLECTION {name: $name}) SET c.updated_at = timestamp()", {"name": collection_name}, rows_in=1)

    async def create_data_points(self, collection_name: str, data_points: list[Any]):
        for point in data_points:
            await self.add_node(point, None)
        return None

    async def retrieve(self, collection_name: str, data_point_ids: list[str]):
        return await self.get_nodes([str(data_point_id) for data_point_id in data_point_ids])

    async def search(
        self,
        collection_name: str,
        query_text: Optional[str],
        query_vector: Optional[list[float]],
        limit: Optional[int],
        with_vector: bool = False,
        include_payload: bool = False,
        node_name: Optional[list[str]] = None,
        node_name_filter_operator: str = "OR",
    ):
        if query_vector is None:
            if query_text is None:
                raise FalkorQueryError("search requires query_text or query_vector")
            query_vector = (await self.embed_data([query_text]))[0]
        rows = self._run_cypher("search", *vector_query(collection_name, query_vector, limit or 10), rows_in=1, read_only=True)
        results = []
        vector_property = collection_parts(collection_name).vector_property
        for row in rows:
            props = self._props(row[0])
            payload = props if include_payload else None
            if with_vector and payload is not None:
                payload["vector"] = props.get(vector_property)
            results.append(ScoredResult(id=self._uuid(props.get("id")), score=float(row[1]), payload=payload))
        return results

    async def batch_search(
        self,
        collection_name: str,
        query_texts: list[str],
        limit: Optional[int],
        with_vectors: bool = False,
        include_payload: bool = False,
        node_name: Optional[list[str]] = None,
    ):
        return [
            await self.search(collection_name, text, None, limit, with_vectors, include_payload, node_name)
            for text in query_texts
        ]

    async def delete_data_points(self, collection_name: str, data_point_ids: list[UUID]):
        self._run_cypher("delete_data_points", *cy.delete_nodes([str(point_id) for point_id in data_point_ids]), rows_in=len(data_point_ids))
    async def prune(self):
        self._run_cypher("prune", "MATCH (c:FCA_COLLECTION) RETURN count(c)", {}, read_only=True)
    async def embed_data(self, data: list[str]) -> list[list[float]]:
        raise FalkorQueryError("embed_data requires an external embedding engine; pass query_vector")
    def _node_payload(self, node: Any, properties: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
        if isinstance(node, tuple) and len(node) == 2:
            return str(node[0]), dict(node[1] or {})
        if isinstance(node, str):
            return node, dict(properties or {})
        if hasattr(node, "model_dump"):
            dumped = node.model_dump()
            return str(dumped.get("id", getattr(node, "id"))), dumped
        raise FalkorQueryError(f"Unsupported node payload: {node!r}")
    @staticmethod
    def _props(entity: Any) -> dict[str, Any]:
        props = getattr(entity, "properties", entity)
        return dict(props or {})

    def _node_tuple(self, node: Any) -> tuple[str, dict[str, Any]]:
        props = self._props(node)
        return str(props.get("id")), props
    @staticmethod
    def _edge_tuple(row: Any) -> tuple[str, str, str, dict[str, Any]]:
        return (str(row[0]), str(row[1]), str(row[2]), dict(row[3] or {}))
    @staticmethod
    def _uuid(value: Any) -> UUID:
        try:
            return UUID(str(value))
        except Exception:
            return uuid5(NAMESPACE_URL, str(value))
