"""Role matrices for Archie dataset-level authority checks.

Dynamic ``session_*`` and ``investigation_*`` reads are a v0.1 approximation:
the adapter receives only a role and dataset, not a caller principal or ownership
record, so dynamic datasets are READ-by-any-role and WRITE-only-by-archie.

# v0.2: add caller principal context plus an ownership table, then narrow
# dynamic reads to datasets owned by that principal.
"""

from __future__ import annotations

from enum import Enum

from fca.datasets import is_archie_dynamic


class Role(str, Enum):
    INGESTOR = "ingestor"
    VALIDATOR = "validator"
    ARCHIE = "archie"


WRITE_MATRIX: dict[Role, frozenset[str]] = {
    Role.INGESTOR: frozenset({"canon", "exemplars", "ingestion_metadata"}),
    Role.VALIDATOR: frozenset({"lessons", "canon_errata"}),
    Role.ARCHIE: frozenset({"quarantine"}),
}

READ_MATRIX: dict[Role, frozenset[str]] = {
    Role.INGESTOR: frozenset({"canon", "exemplars", "ingestion_metadata"}),
    Role.VALIDATOR: frozenset(
        {"canon", "exemplars", "lessons", "canon_errata", "quarantine", "ingestion_metadata"}
    ),
    Role.ARCHIE: frozenset({"canon", "exemplars", "lessons", "canon_errata", "quarantine"}),
}


def can_write(role: Role, dataset: str) -> bool:
    """True if role is permitted to write the dataset."""
    return dataset in WRITE_MATRIX[role] or (role is Role.ARCHIE and is_archie_dynamic(dataset))


def can_read(role: Role, dataset: str) -> bool:
    """True if role is permitted to read the dataset.

    Dynamic Archie datasets are treated as readable for all roles in v0.1 because
    the adapter only receives a dataset name, not an ownership principal.
    """
    return dataset in READ_MATRIX[role] or is_archie_dynamic(dataset)
