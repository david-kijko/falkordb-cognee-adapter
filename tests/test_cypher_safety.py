from __future__ import annotations

import pytest


def test_safe_label_rejects_injection_patterns():
    """SP3: labels with quotes, parens, semicolons, etc. raise FalkorSchemaError."""
    from fca.cypher import safe_label
    from fca.exceptions import FalkorSchemaError

    bad_labels = [
        "foo bar",
        "foo'bar",
        "foo;DROP",
        "foo)",
        "foo(",
        "lower_case",
        "",
        "; DELETE *",
        "1foo",
        "foo`bar",
    ]
    for bad in bad_labels:
        with pytest.raises(FalkorSchemaError):
            safe_label(bad)


def test_safe_label_accepts_valid():
    valid = ["FOO", "FOO_BAR", "F123", "_PRIVATE"]
    from fca.cypher import safe_label

    for v in valid:
        assert safe_label(v) == v


@pytest.mark.asyncio
async def test_user_data_goes_through_params(falkordb_test):
    """SP3: malicious payload is parameterized data and round-trips intact."""
    malicious = "\"; DROP GRAPH; --"

    await falkordb_test.add_node("evil", {"type": "TEST_NODE", "name": malicious})
    node = await falkordb_test.get_node("evil")

    assert node is not None
    assert node["name"] == malicious
