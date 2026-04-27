from __future__ import annotations

import pytest

from fca.adapter import FalkorCogneeAdapter
from fca.roles import Role


@pytest.mark.parametrize(
    "cypher",
    [
        "CREATE (n:Foo)",
        "MERGE (n:Bar)",
        "MATCH (n) DELETE n",
        "MATCH (n) SET n.x = 1",
        "DROP INDEX foo",
        "CALL db.idx.vector.create('Foo', 'bar', 1024, 'cosine')",
        "match (n) create (m)",
    ],
)
def test_assert_read_safe_rejects_write_tokens(cypher):
    from fca.exceptions import QueryGuardError
    from fca.query_guard import assert_read_safe

    with pytest.raises(QueryGuardError):
        assert_read_safe(cypher)


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (n) RETURN n",
        "MATCH (a)-[r]->(b) RETURN a.id, b.id",
        "MATCH (n) WHERE n.name = $name RETURN n LIMIT 10",
    ],
)
def test_assert_read_safe_accepts_read_only(cypher):
    from fca.query_guard import assert_read_safe

    assert assert_read_safe(cypher) is None


@pytest.mark.parametrize(
    ("cypher", "expect_rejected"),
    [
        ("RETURN 'CREATE'", True),
        ("// CREATE foo", True),
        ("/* CREATE bar */", True),
        ("MATCH (CreateUser) RETURN n", True),
        ("MATCH (n) RETURN n.create_date", False),
    ],
)
def test_query_guard_documented_policy(cypher, expect_rejected):
    """v0.1 is conservative: reject regex write tokens regardless of context.

    Slice 7 may upgrade this to a real Cypher parser.
    """
    from fca.exceptions import QueryGuardError
    from fca.query_guard import assert_read_safe

    if expect_rejected:
        with pytest.raises(QueryGuardError):
            assert_read_safe(cypher)
    else:
        assert assert_read_safe(cypher) is None


@pytest.mark.asyncio
async def test_query_in_read_mode_raises_on_write_cypher(falkordb_test):
    """End-to-end: adapter.query("CREATE ...") raises QueryGuardError before driver."""
    from fca.exceptions import QueryGuardError

    with pytest.raises(QueryGuardError):
        await falkordb_test.query("CREATE (:ShouldNotExist {id: 'nope'})", {})


@pytest.mark.asyncio
async def test_internal_write_path_works(falkordb_test):
    """Internal _query_write bypasses assert_read_safe and writes when role permits write."""
    adapter = FalkorCogneeAdapter(
        host=falkordb_test.host,
        port=falkordb_test.port,
        password=falkordb_test.password,
        graph_name="session_query_guard",
        role=Role.ARCHIE,
        socket_timeout=2,
        connection_timeout=1,
    )

    await adapter._query_write("CREATE (:QueryGuardSmoke {id: $id})", {"id": "ok"})
    rows = await adapter.query("MATCH (n:QueryGuardSmoke {id: $id}) RETURN n.id", {"id": "ok"})

    assert rows[0][0] == "ok"
