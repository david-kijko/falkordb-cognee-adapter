"""FalkorDB vector-index helpers for the hybrid adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fca import _cypher_builders as graph_cypher
from fca.cypher import safe_property_name
from fca.exceptions import FalkorEmbeddingError, FalkorQueryError, FalkorSchemaError


@dataclass(frozen=True)
class VectorCollection:
    name: str
    type_name: str
    field_name: str
    label: str
    vector_property: str


def collection_parts(collection_name: str) -> VectorCollection:
    """Map ``<DataPointType>_<field>`` to the graph label and vector property."""
    if "_" in collection_name:
        type_name, field_name = collection_name.rsplit("_", 1)
    else:
        type_name, field_name = collection_name, "embedding"
    if not type_name or not field_name:
        raise FalkorSchemaError(f"Invalid vector collection name: {collection_name!r}")
    label = graph_cypher.node_label({"type": type_name})
    vector_property = safe_property_name(f"{field_name}_vector")
    return VectorCollection(collection_name, type_name, field_name, label, vector_property)


def validate_vector_dimension(vector: list[float], expected: int) -> list[float]:
    values = [float(value) for value in vector]
    if len(values) != expected:
        raise FalkorEmbeddingError(
            f"Vector dimension mismatch: got {len(values)}, expected {expected}"
        )
    return values


class VectorIndexManager:
    """Encapsulates FalkorDB node vector index creation/drop/search metadata."""

    similarity_function = "cosine"

    def __init__(self, session, embedding_engine) -> None:
        self._session = session
        self._embedding_engine = embedding_engine
        self._dimensions: dict[str, int] = {}

    def dimension(self, collection_name: str) -> int:
        return self._dimensions.get(collection_name, self._embedding_engine.get_vector_size())

    def has_collection(self, collection_name: str) -> bool:
        collection = collection_parts(collection_name)
        return any(
            label == collection.label and collection.vector_property in fields
            for label, fields in self._iter_index_fields()
        )

    def ensure_index(self, collection_name: str) -> None:
        collection = collection_parts(collection_name)
        dimension = self.dimension(collection_name)
        if dimension <= 0:
            raise FalkorSchemaError("Vector dimension must be positive")
        if not self.has_collection(collection_name):
            self._session.create_node_vector_index(
                collection.label,
                collection.vector_property,
                dim=dimension,
                similarity_function=self.similarity_function,
            )
        self._dimensions[collection.name] = dimension

    def drop_collection(self, collection_name: str) -> None:
        collection = collection_parts(collection_name)
        if self.has_collection(collection_name):
            self._session.drop_node_vector_index(collection.label, collection.vector_property)
        self._dimensions.pop(collection.name, None)

    def drop_all_vector_indexes(self) -> list[tuple[str, str]]:
        dropped: list[tuple[str, str]] = []
        for label, fields in self._iter_index_fields():
            for field in fields:
                if str(field).endswith("_vector"):
                    self._session.drop_node_vector_index(label, field)
                    dropped.append((label, field))
        self._dimensions.clear()
        return dropped

    def _iter_index_fields(self):
        try:
            indices = self._session.list_indices().result_set or []
        except FalkorQueryError as exc:
            if "Invalid graph operation on empty key" in str(exc):
                return
            raise
        for row in indices:
            label = row[0] if len(row) > 0 else None
            fields = row[1] if len(row) > 1 else []
            if isinstance(label, str) and isinstance(fields, list):
                yield label, fields


def upsert_vectors(collection_name: str, items: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    collection = collection_parts(collection_name)
    return (
        f"UNWIND $items AS item MERGE (node:{collection.label} {{id: item.id}}) "
        "SET node += item.payload, "
        f"node.{collection.vector_property} = vecf32(item.vector), "
        "node.updated_at = timestamp()",
        {"items": items},
    )


def retrieve_vectors(collection_name: str, data_point_ids: list[str]) -> tuple[str, dict[str, Any]]:
    collection = collection_parts(collection_name)
    return (
        f"MATCH (node:{collection.label}) WHERE node.id IN $ids "
        f"AND node.{collection.vector_property} IS NOT NULL RETURN node",
        {"ids": [str(data_point_id) for data_point_id in data_point_ids]},
    )


def vector_query(collection_name: str, query_vector: list[float], limit: int) -> tuple[str, dict[str, Any]]:
    collection = collection_parts(collection_name)
    return (
        "CALL db.idx.vector.queryNodes($label, $property, $limit, vecf32($query_vector)) "
        "YIELD node, score RETURN node, score",
        {
            "label": collection.label,
            "property": collection.vector_property,
            "limit": int(limit),
            "query_vector": [float(value) for value in query_vector],
        },
    )


def delete_vectors(collection_name: str, data_point_ids: list[str]) -> tuple[str, dict[str, Any]]:
    collection = collection_parts(collection_name)
    return (
        f"MATCH (node:{collection.label}) WHERE node.id IN $ids "
        f"SET node.{collection.vector_property} = NULL",
        {"ids": [str(data_point_id) for data_point_id in data_point_ids]},
    )


def clear_vector_property(label: str, vector_property: str) -> tuple[str, dict[str, Any]]:
    return f"MATCH (node:{label}) SET node.{safe_property_name(vector_property)} = NULL", {}
