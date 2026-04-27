"""Unit tests for Cypher parameter sanitization.

These tests verify that Enum values in query parameters are properly
converted to their underlying values before being sent to FalkorDB.
No FalkorDB connection is required.
"""

from enum import Enum

from cognee_community_hybrid_adapter_falkor.falkor_adapter import FalkorDBAdapter


class Color(Enum):
    RED = "red"
    GREEN = "green"


class Priority(Enum):
    LOW = 1
    HIGH = 2


def test_enum_string_value():
    result = FalkorDBAdapter._sanitize_cypher_params({"color": Color.RED})
    assert result == {"color": "red"}


def test_enum_int_value():
    result = FalkorDBAdapter._sanitize_cypher_params({"priority": Priority.HIGH})
    assert result == {"priority": 2}


def test_plain_values_unchanged():
    params = {"name": "Alice", "age": 30, "active": True}
    result = FalkorDBAdapter._sanitize_cypher_params(params)
    assert result == params


def test_nested_dict_with_enum():
    params = {"meta": {"color": Color.GREEN, "label": "test"}}
    result = FalkorDBAdapter._sanitize_cypher_params(params)
    assert result == {"meta": {"color": "green", "label": "test"}}


def test_list_with_enums():
    params = {"colors": [Color.RED, Color.GREEN, "blue"]}
    result = FalkorDBAdapter._sanitize_cypher_params(params)
    assert result == {"colors": ["red", "green", "blue"]}


def test_empty_dict():
    assert FalkorDBAdapter._sanitize_cypher_params({}) == {}


def test_mixed_complex():
    params = {
        "name": "node1",
        "status": Color.RED,
        "tags": [Color.GREEN, "manual"],
        "nested": {"priority": Priority.LOW, "value": 42},
    }
    result = FalkorDBAdapter._sanitize_cypher_params(params)
    assert result == {
        "name": "node1",
        "status": "red",
        "tags": ["green", "manual"],
        "nested": {"priority": 1, "value": 42},
    }
