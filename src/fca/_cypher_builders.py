"""Pure Cypher builders for FalkorCogneeAdapter operations."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from enum import Enum
from typing import Any
from uuid import UUID

from fca.cypher import safe_label, safe_property_name, safe_reltype
from fca.exceptions import FalkorSchemaError


Cypher = tuple[str, dict[str, Any]]


def _clean_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, list):
        return [_clean_value(item) for item in value]
    return value


def clean_properties(properties: dict[str, Any] | None) -> dict[str, Any]:
    return {str(key): _clean_value(value) for key, value in (properties or {}).items() if value is not None}


def _camel_to_label(value: str) -> str:
    label = re.sub(r"(?<!^)(?=[A-Z])", "_", value).upper()
    return safe_label(label)


def node_label(properties: dict[str, Any] | None) -> str:
    raw = (properties or {}).get("type", "NODE")
    if not isinstance(raw, str):
        raise FalkorSchemaError(f"Node type must be a string label, got {raw!r}")
    try:
        return safe_label(raw)
    except FalkorSchemaError:
        if re.fullmatch(r"[A-Z][A-Za-z0-9]*", raw):
            return _camel_to_label(raw)
        raise


def add_node(node_id: str, properties: dict[str, Any] | None) -> Cypher:
    label = node_label(properties)
    props = {"id": str(node_id), **clean_properties(properties)}
    return (
        f"MERGE (node:{label} {{id: $node_id}}) "
        "SET node += $properties, node.updated_at = timestamp()",
        {"node_id": str(node_id), "properties": props},
    )


def grouped_add_nodes(nodes: list[tuple[str, dict[str, Any]]]) -> list[Cypher]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node_id, properties in nodes:
        grouped[node_label(properties)].append(
            {"id": str(node_id), "properties": {"id": str(node_id), **clean_properties(properties)}}
        )
    return [
        (
            f"UNWIND $items AS item MERGE (node:{label} {{id: item.id}}) "
            "SET node += item.properties, node.updated_at = timestamp()",
            {"items": items},
        )
        for label, items in grouped.items()
    ]


def add_edges(edges: list[tuple[str, str, str, dict[str, Any] | None]]) -> list[Cypher]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source_id, target_id, relationship, properties in edges:
        rel = safe_reltype(relationship)
        props = {
            "relationship_name": relationship,
            "source_node_id": str(source_id),
            "target_node_id": str(target_id),
            **clean_properties(properties),
        }
        grouped[rel].append({"source_id": str(source_id), "target_id": str(target_id), "props": props})
    return [
        (
            f"UNWIND $items AS item MERGE (source {{id: item.source_id}}) "
            f"MERGE (target {{id: item.target_id}}) MERGE (source)-[r:{rel}]->(target) "
            "SET r += item.props, r.updated_at = timestamp()",
            {"items": items},
        )
        for rel, items in grouped.items()
    ]


def delete_node(node_id: str) -> Cypher:
    return "MATCH (node {id: $node_id}) DETACH DELETE node", {"node_id": str(node_id)}


def delete_nodes(node_ids: list[str]) -> Cypher:
    return "MATCH (node) WHERE node.id IN $node_ids DETACH DELETE node", {
        "node_ids": [str(node_id) for node_id in node_ids]
    }


def get_node(node_id: str) -> Cypher:
    return "MATCH (node) WHERE node.id = $node_id RETURN node", {"node_id": str(node_id)}


def get_nodes(node_ids: list[str]) -> Cypher:
    return "MATCH (node) WHERE node.id IN $node_ids RETURN node", {
        "node_ids": [str(node_id) for node_id in node_ids]
    }


def get_neighbors(node_id: str) -> Cypher:
    return (
        "MATCH (node)-[]-(neighbor) WHERE node.id = $node_id RETURN DISTINCT neighbor",
        {"node_id": str(node_id)},
    )


def get_edges(node_id: str) -> Cypher:
    return (
        "MATCH (n)-[r]-(m) WHERE n.id = $node_id "
        "RETURN startNode(r).id, endNode(r).id, type(r), properties(r)",
        {"node_id": str(node_id)},
    )


def has_edge(source_id: str, target_id: str, relationship_name: str) -> Cypher:
    rel = safe_reltype(relationship_name)
    return (
        f"MATCH (source)-[r:{rel}]->(target) "
        "WHERE source.id = $source_id AND target.id = $target_id "
        "RETURN count(r) > 0",
        {"source_id": str(source_id), "target_id": str(target_id)},
    )


def get_connections(node_id: str) -> Cypher:
    return (
        "MATCH (a)-[r]-(b) WHERE a.id = $node_id "
        "RETURN a, r, b, startNode(r).id, endNode(r).id, type(r), properties(r)",
        {"node_id": str(node_id)},
    )


def graph_nodes() -> Cypher:
    return "MATCH (n) RETURN n", {}


def graph_edges() -> Cypher:
    return "MATCH (a)-[r]->(b) RETURN a.id, b.id, type(r), properties(r)", {}


def graph_counts() -> Cypher:
    return "MATCH (n) WITH count(n) AS nodes OPTIONAL MATCH ()-[r]->() RETURN nodes, count(r)", {}


def is_empty() -> Cypher:
    return "MATCH (n) RETURN count(n) = 0", {}


def neighborhood_nodes(node_ids: list[str], depth: int, edge_types: list[str] | None = None) -> Cypher:
    if depth < 0:
        raise FalkorSchemaError("Neighborhood depth must be >= 0")
    rel = ""
    if edge_types:
        rel = ":" + "|".join(safe_reltype(edge_type) for edge_type in edge_types)
    return (
        f"MATCH (start) WHERE start.id IN $node_ids "
        f"MATCH path=(start)-[{rel}*0..{int(depth)}]-(n) RETURN DISTINCT n",
        {"node_ids": [str(node_id) for node_id in node_ids]},
    )


def subgraph_edges(node_ids: list[str]) -> Cypher:
    return (
        "MATCH (a)-[r]->(b) WHERE a.id IN $node_ids AND b.id IN $node_ids "
        "RETURN a.id, b.id, type(r), properties(r)",
        {"node_ids": [str(node_id) for node_id in node_ids]},
    )


def filtered_nodes(attribute_filters: list[dict[str, list[str | int]]]) -> Cypher:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    idx = 0
    for filter_group in attribute_filters:
        for prop, values in filter_group.items():
            prop_name = safe_property_name(prop)
            param = f"values_{idx}"
            clauses.append(f"n.{prop_name} IN ${param}")
            params[param] = values
            idx += 1
    where = f" WHERE {' OR '.join(clauses)}" if clauses else ""
    return f"MATCH (n){where} RETURN n", params


def nodeset_nodes(node_type: type[Any], node_name: list[str], operator: str) -> Cypher:
    label = node_label({"type": node_type.__name__})
    if operator not in {"OR", "AND"}:
        raise FalkorSchemaError("node_name_filter_operator must be OR or AND")
    if not node_name:
        return f"MATCH (n:{label}) RETURN id(n), properties(n)", {}
    return (
        f"MATCH (n:{label}) WHERE n.name IN $names RETURN id(n), properties(n)",
        {"names": [str(name) for name in node_name]},
    )
