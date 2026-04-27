from __future__ import annotations

import pytest

from fca.roles import Role


@pytest.mark.parametrize(
    ("dataset", "expect"),
    [
        ("session_uuid-with-dashes", True),
        ("investigation_12345", True),
        ("session_", True),
        ("canon", False),
        ("session", False),
        ("investigation", False),
        ("randomname", False),
    ],
)
def test_archie_prefix_matching(dataset, expect):
    from fca.datasets import is_archie_dynamic

    assert is_archie_dynamic(dataset) is expect


def test_archie_can_write_session_xxx_but_not_random_name():
    """archie role + dataset with archie prefix -> can_write returns True."""
    from fca.roles import can_write

    assert can_write(Role.ARCHIE, "session_xxx") is True
    assert can_write(Role.ARCHIE, "random_name") is False
