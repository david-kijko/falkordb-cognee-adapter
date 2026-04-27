"""Small result containers shared by the adapter and tests."""

from __future__ import annotations


class ResultList(list):
    """Plain list with a ``result_set`` alias for Cognee/upstream compatibility."""

    @property
    def result_set(self):
        return self
