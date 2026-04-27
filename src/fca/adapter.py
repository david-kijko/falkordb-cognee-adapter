"""Cognee 1.0.3 hybrid graph/vector adapter for FalkorDB."""

import functools
import time
from typing import Any, Dict, List, Optional, Tuple, Type, Union
from uuid import NAMESPACE_URL, UUID, uuid5

from cognee.infrastructure.databases.graph.graph_db_interface import GraphDBInterface
from cognee.infrastructure.databases.vector.models.ScoredResult import ScoredResult
from cognee.infrastructure.databases.vector.vector_db_interface import VectorDBInterface
from cognee.infrastructure.engine.models.DataPoint import DataPoint

from fca import _cypher_builders as cy
from fca._authority import assert_can_read, assert_can_write, guarded_op
from fca._falkor_session import FalkorSession
from fca._vector_index import (
    VectorIndexManager,
    clear_vector_property,
    collection_parts,
    delete_vectors,
    retrieve_vectors,
    upsert_vectors,
    validate_vector_dimension,
    vector_query,
)
from fca.embeddings import OllamaEmbeddingEngine
from fca.exceptions import FalkorEmbeddingError, FalkorQueryError
from fca.isolation import DatasetIsolationStrategy, GraphPerDataset
from fca.query_guard import assert_read_safe
from fca._result import ResultList
from fca.roles import Role
from fca.telemetry import NullSink, TelemetrySink

def telemetry_op(func):
    """Emit exactly one telemetry event per public adapter method call."""
    @functools.wraps(func)
    async def wrapper(self, *args, **kwargs):
        start = time.perf_counter()
        if func.__name__ == "query" and len(args) == 1 and "params" not in kwargs:
            args = (args[0], {})
        try:
            result = await func(self, *args, **kwargs)
        except Exception as exc:
            self._emit(
                func.__name__,
                latency_ms=(time.perf_counter() - start) * 1000,
                failure_class=getattr(exc, "failure_class", exc.__class__.__name__),
            )
            raise
        self._emit(func.__name__, latency_ms=(time.perf_counter() - start) * 1000, rows_out=self._rows_out(result))
        return result
    return wrapper
read_op = guarded_op(telemetry_op, "_read_guard")
write_op = guarded_op(telemetry_op, "_write_guard")
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
        self.embedding_engine = OllamaEmbeddingEngine()
        self._session = FalkorSession(
            host=host,
            port=port,
            password=password,
            graph_name=graph_name,
            socket_timeout=socket_timeout,
            connection_timeout=connection_timeout,
        )
        self._vectors = VectorIndexManager(self._session, self.embedding_engine)

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

    def _emit(self, op: str, **fields: Any) -> None:
        self.telemetry.emit(self._event(op, **fields))

    def _read_guard(self, dataset: str) -> None:
        assert_can_read(self.role, dataset)

    def _write_guard(self, dataset: str) -> None:
        assert_can_write(self.role, dataset)

    def _execute(
        self,
        statement: str,
        params: dict[str, Any] | None = None,
        *,
        read_only: bool = False,
    ) -> ResultList:
        raw = self._session.execute(statement, params or {}, read_only=read_only)
        return ResultList(raw.result_set or [])

    @read_op
    async def query(self, query: str, params: dict) -> List[Any]:
        assert_read_safe(query)
        return self._execute(query, params or {}, read_only=True)

    async def _query_write(self, query: str, params: dict | None = None) -> List[Any]:
        self._write_guard(self.graph_name)
        return self._execute(query, params or {})

    @read_op
    async def is_empty(self) -> bool:
        if self.graph_name not in self._session.list_graphs():
            return True
        rows = self._execute(*cy.is_empty(), read_only=True)
        return bool(rows[0][0]) if rows else True

    @write_op
    async def add_node(
        self, node: Union[DataPoint, str], properties: Optional[Dict[str, Any]] = None
    ) -> None:
        node_id, props = self._node_payload(node, properties)
        self._execute(*cy.add_node(node_id, props))

    @write_op
    async def add_nodes(
        self, nodes: Union[List[Tuple[str, Dict[str, Any]]], List[DataPoint]]
    ) -> None:
        normalized = [self._node_payload(node, None) for node in nodes]
        for statement, params in cy.grouped_add_nodes(normalized):
            self._execute(statement, params)

    @write_op
    async def delete_node(self, node_id: str) -> None:
        self._execute(*cy.delete_node(node_id))

    @write_op
    async def delete_nodes(self, node_ids: List[str]) -> None:
        self._execute(*cy.delete_nodes(node_ids))

    @read_op
    async def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        rows = self._execute(*cy.get_node(node_id), read_only=True)
        return self._props(rows[0][0]) if rows else None

    @read_op
    async def get_nodes(self, node_ids: List[str]) -> List[Dict[str, Any]]:
        rows = self._execute(*cy.get_nodes(node_ids), read_only=True)
        return [self._props(row[0]) for row in rows]

    @write_op
    async def add_edge(
        self,
        source_id: str,
        target_id: str,
        relationship_name: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> None:
        for statement, params in cy.add_edges([(source_id, target_id, relationship_name, properties or {})]):
            self._execute(statement, params)

    @write_op
    async def add_edges(
        self,
        edges: Union[
            List[Tuple[str, str, str, Dict[str, Any]]],
            List[Tuple[str, str, str, Optional[Dict[str, Any]]]],
        ],
    ) -> None:
        for statement, params in cy.add_edges(edges):
            self._execute(statement, params)

    @write_op
    async def delete_graph(self) -> None:
        self._session.delete_graph()

    @read_op
    async def get_graph_data(
        self,
    ) -> Tuple[List[Tuple[str, Dict[str, Any]]], List[Tuple[str, str, str, Dict[str, Any]]]]:
        node_rows = self._execute(*cy.graph_nodes(), read_only=True)
        edge_rows = self._execute(*cy.graph_edges(), read_only=True)
        return ([self._node_tuple(row[0]) for row in node_rows], [self._edge_tuple(row) for row in edge_rows])

    @read_op
    async def get_graph_metrics(self, include_optional: bool = False) -> Dict[str, Any]:
        rows = self._execute(*cy.graph_counts(), read_only=True)
        metrics = {"num_nodes": 0, "num_edges": 0}
        if rows:
            metrics = {"num_nodes": rows[0][0], "num_edges": rows[0][1]}
        if include_optional:
            label_rows = self._execute("MATCH (n) RETURN labels(n)", {}, read_only=True)
            metrics["labels"] = sorted({label for row in label_rows for label in row[0]})
        return metrics

    @read_op
    async def has_edge(self, source_id: str, target_id: str, relationship_name: str) -> bool:
        rows = self._execute(*cy.has_edge(source_id, target_id, relationship_name), read_only=True)
        return bool(rows[0][0]) if rows else False

    @read_op
    async def has_edges(
        self, edges: List[Tuple[str, str, str, Dict[str, Any]]]
    ) -> List[Tuple[str, str, str, Dict[str, Any]]]:
        present = []
        for edge in edges:
            rows = self._execute(*cy.has_edge(edge[0], edge[1], edge[2]), read_only=True)
            if rows and bool(rows[0][0]):
                present.append(edge)
        return present

    @read_op
    async def get_edges(self, node_id: str) -> List[Tuple[str, str, str, Dict[str, Any]]]:
        rows = self._execute(*cy.get_edges(node_id), read_only=True)
        return [self._edge_tuple(row) for row in rows]

    @read_op
    async def get_neighbors(self, node_id: str) -> List[Dict[str, Any]]:
        rows = self._execute(*cy.get_neighbors(node_id), read_only=True)
        return [self._props(row[0]) for row in rows]

    @read_op
    async def get_nodeset_subgraph(
        self, node_type: Type[Any], node_name: List[str], node_name_filter_operator: str = "OR"
    ) -> Tuple[List[Tuple[int, dict]], List[Tuple[int, int, str, dict]]]:
        rows = self._execute(*cy.nodeset_nodes(node_type, node_name, node_name_filter_operator), read_only=True)
        return ([(row[0], row[1]) for row in rows], [])

    @read_op
    async def get_connections(
        self, node_id: Union[str, UUID]
    ) -> List[Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]]:
        rows = self._execute(*cy.get_connections(str(node_id)), read_only=True)
        return [(self._props(row[0]), self._props(row[1]), self._props(row[2])) for row in rows]

    @read_op
    async def get_neighborhood(
        self, node_ids: List[str], depth: int = 1, edge_types: Optional[List[str]] = None
    ) -> Tuple[List[Tuple[str, Dict[str, Any]]], List[Tuple[str, str, str, Dict[str, Any]]]]:
        node_rows = self._execute(*cy.neighborhood_nodes(node_ids, depth, edge_types), read_only=True)
        nodes = [self._node_tuple(row[0]) for row in node_rows]
        edge_rows = self._execute(*cy.subgraph_edges([node_id for node_id, _ in nodes]), read_only=True)
        return nodes, [self._edge_tuple(row) for row in edge_rows]

    @read_op
    async def get_filtered_graph_data(
        self, attribute_filters: List[Dict[str, List[Union[str, int]]]]
    ) -> Tuple[List[Tuple[str, Dict[str, Any]]], List[Tuple[str, str, str, Dict[str, Any]]]]:
        node_rows = self._execute(*cy.filtered_nodes(attribute_filters), read_only=True)
        nodes = [self._node_tuple(row[0]) for row in node_rows]
        edge_rows = self._execute(*cy.subgraph_edges([node_id for node_id, _ in nodes]), read_only=True)
        return nodes, [self._edge_tuple(row) for row in edge_rows]

    @read_op
    async def has_collection(self, collection_name: str) -> bool:
        return self._vectors.has_collection(collection_name)

    @write_op
    async def create_collection(self, collection_name: str, payload_schema: Optional[Any] = None):
        self._vectors.ensure_index(collection_name)
        self._execute("MERGE (c:FCA_COLLECTION {name: $name}) SET c.updated_at = timestamp()", {"name": collection_name})

    @write_op
    async def create_data_points(self, collection_name: str, data_points: List[DataPoint]):
        if not data_points:
            return None
        await self._create_collection(collection_name)
        collection = collection_parts(collection_name)
        texts = [str(getattr(point, collection.field_name)) for point in data_points]
        vectors = await self.embedding_engine.embed_text(texts)
        expected = self._vectors.dimension(collection_name)
        items = []
        for point, vector in zip(data_points, vectors, strict=True):
            point_id, payload = self._node_payload(point, None)
            payload["id"] = point_id
            payload["type"] = collection.type_name
            payload.pop(collection.vector_property, None)
            items.append(
                {
                    "id": point_id,
                    "payload": payload,
                    "vector": validate_vector_dimension(vector, expected),
                }
            )
        self._execute(*upsert_vectors(collection_name, items))
        return None

    @read_op
    async def retrieve(self, collection_name: str, data_point_ids: list[str]):
        rows = self._execute(*retrieve_vectors(collection_name, data_point_ids), read_only=True)
        collection = collection_parts(collection_name)
        return [
            ScoredResult(id=self._uuid(self._props(row[0]).get("id")), score=0.0, payload=self._payload(row[0], collection.vector_property))
            for row in rows
        ]

    @read_op
    async def search(
        self,
        collection_name: str,
        query_text: Optional[str],
        query_vector: Optional[List[float]],
        limit: Optional[int],
        with_vector: bool = False,
        include_payload: bool = False,
        node_name: Optional[List[str]] = None,
        node_name_filter_operator: str = "OR",
    ):
        if not self._vectors.has_collection(collection_name):
            raise FalkorEmbeddingError(f"Vector collection does not exist: {collection_name}")
        if query_vector is None:
            if query_text is None:
                raise FalkorQueryError("search requires query_text or query_vector")
            query_vector = (await self.embedding_engine.embed_text([query_text]))[0]
        expected = self._vectors.dimension(collection_name)
        query_vector = validate_vector_dimension(query_vector, expected)
        collection = collection_parts(collection_name)
        rows = self._execute(*vector_query(collection_name, query_vector, limit or 10), read_only=True)
        results = []
        for row in rows:
            props = self._props(row[0])
            if node_name and not self._matches_node_filter(props, node_name, node_name_filter_operator):
                continue
            payload = self._payload(row[0], collection.vector_property) if include_payload else None
            results.append(ScoredResult(id=self._uuid(props.get("id")), score=float(row[1]), payload=payload))
        return results[: limit or len(results)]

    @read_op
    async def batch_search(
        self,
        collection_name: str,
        query_texts: List[str],
        limit: Optional[int],
        with_vectors: bool = False,
        include_payload: bool = False,
        node_name: Optional[List[str]] = None,
    ):
        vectors = await self.embedding_engine.embed_text(query_texts) if query_texts else []
        return [
            await self._search_no_telemetry(collection_name, vector, limit, include_payload=include_payload, node_name=node_name)
            for vector in vectors
        ]

    @write_op
    async def delete_data_points(self, collection_name: str, data_point_ids: List[UUID]):
        self._execute(*delete_vectors(collection_name, [str(point_id) for point_id in data_point_ids]))

    @write_op
    async def prune(self):
        dropped = self._vectors.drop_all_vector_indexes()
        for label, vector_property in dropped:
            self._execute(*clear_vector_property(label, vector_property))
        self._execute("MATCH (c:FCA_COLLECTION) DETACH DELETE c", {})

    @read_op
    async def embed_data(self, data: List[str]) -> List[List[float]]:
        return await self.embedding_engine.embed_text(data)

    @write_op
    async def create_vector_index(self, index_name: str, index_property_name: str):
        await self._create_collection(f"{index_name}_{index_property_name}")

    @write_op
    async def index_data_points(
        self, index_name: str, index_property_name: str, data_points: List[DataPoint]
    ):
        await self._create_data_points(f"{index_name}_{index_property_name}", data_points)

    async def _create_collection(self, collection_name: str) -> None:
        self._vectors.ensure_index(collection_name)
        self._execute("MERGE (c:FCA_COLLECTION {name: $name}) SET c.updated_at = timestamp()", {"name": collection_name})

    async def _create_data_points(self, collection_name: str, data_points: List[DataPoint]) -> None:
        if not data_points:
            return None
        collection = collection_parts(collection_name)
        await self._create_collection(collection_name)
        texts = [str(getattr(point, collection.field_name)) for point in data_points]
        vectors = await self.embedding_engine.embed_text(texts)
        expected = self._vectors.dimension(collection_name)
        items = []
        for point, vector in zip(data_points, vectors, strict=True):
            point_id, payload = self._node_payload(point, None)
            payload["id"] = point_id
            payload["type"] = collection.type_name
            items.append({"id": point_id, "payload": payload, "vector": validate_vector_dimension(vector, expected)})
        self._execute(*upsert_vectors(collection_name, items))
        return None

    async def _search_no_telemetry(
        self,
        collection_name: str,
        query_vector: List[float],
        limit: Optional[int],
        *,
        include_payload: bool,
        node_name: Optional[List[str]],
    ):
        if not self._vectors.has_collection(collection_name):
            raise FalkorEmbeddingError(f"Vector collection does not exist: {collection_name}")
        expected = self._vectors.dimension(collection_name)
        query_vector = validate_vector_dimension(query_vector, expected)
        collection = collection_parts(collection_name)
        rows = self._execute(*vector_query(collection_name, query_vector, limit or 10), read_only=True)
        results = []
        for row in rows:
            props = self._props(row[0])
            if node_name and not self._matches_node_filter(props, node_name, "OR"):
                continue
            payload = self._payload(row[0], collection.vector_property) if include_payload else None
            results.append(ScoredResult(id=self._uuid(props.get("id")), score=float(row[1]), payload=payload))
        return results[: limit or len(results)]

    def _node_payload(self, node: Any, properties: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
        if isinstance(node, tuple) and len(node) == 2:
            return str(node[0]), dict(cy.clean_properties(node[1] or {}))
        if isinstance(node, str):
            return node, dict(cy.clean_properties(properties or {}))
        if hasattr(node, "model_dump"):
            dumped = cy.clean_properties(node.model_dump())
            node_id = str(dumped.get("id", getattr(node, "id")))
            return node_id, dumped
        raise FalkorQueryError(f"Unsupported node payload: {node!r}")

    @staticmethod
    def _props(entity: Any) -> dict[str, Any]:
        props = getattr(entity, "properties", entity)
        return dict(props or {})

    def _payload(self, node: Any, vector_property: str) -> dict[str, Any]:
        payload = self._props(node)
        payload.pop(vector_property, None)
        return payload

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

    @staticmethod
    def _matches_node_filter(props: dict[str, Any], node_name: List[str], operator: str) -> bool:
        belongs = props.get("belongs_to_set") or []
        if isinstance(belongs, str):
            belongs = [belongs]
        matches = [name in belongs for name in node_name]
        return all(matches) if operator == "AND" else any(matches)

    @staticmethod
    def _rows_out(result: Any) -> int | None:
        if result is None:
            return 0
        if isinstance(result, bool):
            return 1
        if isinstance(result, tuple):
            return sum(len(item) for item in result if isinstance(item, list))
        if isinstance(result, list):
            return len(result)
        if isinstance(result, dict):
            return 1
        return None
