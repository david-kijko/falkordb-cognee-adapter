"""FalkorDB vector-index helpers for the hybrid adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fca.cypher import safe_label, safe_property_name
from fca.exceptions import FalkorSchemaError


@dataclass(frozen=True)
class VectorCollection:
    name: str
    label: str
    vector_property: str


def collection_parts(collection_name: str) -> VectorCollection:
    """Map a Cognee collection name to a safe FalkorDB label/vector property."""
    if "_" in collection_name:
        raw_label, _, raw_property = collection_name.partition("_")
        label = safe_label(raw_label.upper())
        prop = safe_property_name(f"{raw_property}_vector")
    else:
        label = safe_label(collection_name.upper())
        prop = safe_property_name("embedding_vector")
    return VectorCollection(collection_name, label, prop)


def dimension_from_schema(payload_schema: Any) -> int | None:
    if payload_schema is None:
        return None
    if isinstance(payload_schema, dict):
        for key in ("dimension", "dim", "vector_size", "size"):
            value = payload_schema.get(key)
            if isinstance(value, int) and value > 0:
                return value
    for attr in ("dimension", "dim", "vector_size", "size"):
        value = getattr(payload_schema, attr, None)
        if isinstance(value, int) and value > 0:
            return value
    return None


class VectorIndexManager:
    """Encapsulates FalkorDB HNSW/vector index naming and creation."""

    similarity_function = "cosine"

    def __init__(self, session) -> None:
        self._session = session
        self._dimensions: dict[str, int] = {}

    def index_name(self, collection: VectorCollection) -> str:
        return f"idx_{collection.label.lower()}_{collection.vector_property}"

    def has_collection(self, collection_name: str) -> bool:
        collection = collection_parts(collection_name)
        indices = self._session.list_indices().result_set or []
        for row in indices:
            label = row[0] if len(row) > 0 else None
            fields = row[1] if len(row) > 1 else []
            if label == collection.label and collection.vector_property in fields:
                return True
        return False

    def ensure_index(self, collection_name: str, dimension: int | None) -> None:
        collection = collection_parts(collection_name)
        if dimension is None:
            return
        if dimension <= 0:
            raise FalkorSchemaError("Vector dimension must be positive")
        if self.has_collection(collection_name):
            self._dimensions[collection.name] = dimension
            return
        self._session.create_node_vector_index(
            collection.label,
            collection.vector_property,
            dim=dimension,
            similarity_function=self.similarity_function,
        )
        self._dimensions[collection.name] = dimension


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
