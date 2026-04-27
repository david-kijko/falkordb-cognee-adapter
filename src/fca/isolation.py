"""Dataset isolation strategies for FalkorDB-backed Cognee graphs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from falkordb import FalkorDB

if TYPE_CHECKING:  # pragma: no cover
    from falkordb.graph import Graph


class DatasetIsolationStrategy(ABC):
    """Map logical datasets to FalkorDB graphs.

    v0.2: add TenantPerGraph and SharedGraphWithTenantId strategies.
    """

    @abstractmethod
    def graph_for(self, db: FalkorDB, dataset: str) -> "Graph": ...

    @abstractmethod
    def delete(self, db: FalkorDB, dataset: str) -> None: ...

    @abstractmethod
    def graph_name_for(self, dataset: str) -> str: ...


class GraphPerDataset(DatasetIsolationStrategy):
    """One FalkorDB graph_name per logical dataset. graph_name == dataset (verbatim)."""

    def graph_for(self, db: FalkorDB, dataset: str) -> "Graph":
        return db.select_graph(self.graph_name_for(dataset))

    def delete(self, db: FalkorDB, dataset: str) -> None:
        db.select_graph(self.graph_name_for(dataset)).delete()

    def graph_name_for(self, dataset: str) -> str:
        return dataset
