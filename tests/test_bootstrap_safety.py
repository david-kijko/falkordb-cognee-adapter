"""Safety tests for Slice 5 bootstrap graph creation and deletion."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from falkordb import FalkorDB

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts" / "bootstrap.py"
ROSTER_GRAPHS = {
    "canon",
    "exemplars",
    "ingestion_metadata",
    "lessons",
    "canon_errata",
    "quarantine",
}
OWNER = "falkordb-cognee-adapter"


@pytest.fixture
def db(request) -> Iterator[FalkorDB]:
    try:
        client = FalkorDB(host="127.0.0.1", port=6380, socket_timeout=1, socket_connect_timeout=1)
        client.list_graphs()
    except Exception as exc:  # pragma: no cover - fixture availability
        if request.config.getoption("--require-fixtures"):
            pytest.fail(f"FalkorDB :6380 not reachable; required by --require-fixtures. {exc!r}")
        pytest.skip(f"FalkorDB :6380 not reachable: {exc!r}")
    yield client


def run_bootstrap(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP),
            "--host",
            "127.0.0.1",
            "--port",
            "6380",
            *args,
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def delete_graph(db: FalkorDB, name: str) -> None:
    try:
        db.select_graph(name).delete()
    except Exception:
        pass


def graph_names(db: FalkorDB) -> set[str]:
    return set(db.list_graphs())


@pytest.fixture(autouse=True)
def clean_roster(db: FalkorDB) -> Iterator[None]:
    for name in ROSTER_GRAPHS:
        delete_graph(db, name)
    yield
    for name in ROSTER_GRAPHS:
        delete_graph(db, name)


def test_dry_run_default_creates_nothing(db: FalkorDB) -> None:
    before = graph_names(db)

    result = run_bootstrap()

    assert result.returncode == 0, result.stderr
    assert graph_names(db) == before


def test_create_roster_creates_6_graphs_with_dataset_meta(db: FalkorDB) -> None:
    result = run_bootstrap("--create-roster")

    assert result.returncode == 0, result.stderr
    assert ROSTER_GRAPHS <= graph_names(db)
    for name in ROSTER_GRAPHS:
        rows = db.select_graph(name).query(
            "MATCH (m:DatasetMeta {owner: $owner}) RETURN count(m)", {"owner": OWNER}
        )
        assert rows.result_set == [[1]]


def test_drop_graphs_without_confirm_rejected(db: FalkorDB) -> None:
    name = f"foo_{uuid4().hex}"
    db.select_graph(name).query("CREATE (:Thing {id: 'keep'})")

    result = run_bootstrap("--drop-graphs", name)

    assert result.returncode == 1
    assert name in graph_names(db)
    delete_graph(db, name)


def test_drop_graphs_with_marker_succeeds(db: FalkorDB) -> None:
    name = f"foo_{uuid4().hex}"
    db.select_graph(name).query(
        "CREATE (:DatasetMeta {owner: $owner}), (:Thing {id: 'drop-me'})", {"owner": OWNER}
    )

    result = run_bootstrap("--drop-graphs", name)

    assert result.returncode == 0, result.stderr
    assert name not in graph_names(db)


def test_drop_graphs_without_marker_requires_confirm_fraud(db: FalkorDB) -> None:
    name = f"fraud_{uuid4().hex}"
    db.select_graph(name).query("CREATE (:Thing {id: 'drop-me'})")

    result = run_bootstrap("--drop-graphs", name, "--confirm-drop-fraud", "--yes")

    assert result.returncode == 0, result.stderr
    assert name not in graph_names(db)


def test_unrelated_graphs_never_dropped(db: FalkorDB) -> None:
    unrelated = f"unrelated_{uuid4().hex}"
    db.select_graph(unrelated).query("CREATE (:Thing {id: 'keep'})")

    result = run_bootstrap("--create-roster")

    assert result.returncode == 0, result.stderr
    assert unrelated in graph_names(db)
    delete_graph(db, unrelated)
