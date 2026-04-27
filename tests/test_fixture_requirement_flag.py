from __future__ import annotations


def test_require_fixtures_flag_is_registered(pytestconfig):
    assert isinstance(pytestconfig.getoption("--require-fixtures"), bool)
