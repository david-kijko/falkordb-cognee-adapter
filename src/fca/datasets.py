"""Canonical dataset roster used by later role matrices."""

from __future__ import annotations

CANON_DATASETS: frozenset[str] = frozenset(
    {
        "canon",
        "exemplars",
        "ingestion_metadata",
        "lessons",
        "canon_errata",
        "quarantine",
    }
)

ARCHIE_PREFIXES: tuple[str, ...] = ("session_", "investigation_")


def is_archie_dynamic(dataset: str) -> bool:
    """True if dataset is a session_* or investigation_* prefix-name."""
    return dataset.startswith(ARCHIE_PREFIXES)


def is_known_dataset(dataset: str) -> bool:
    """True if dataset is in the canonical roster OR matches an archie prefix."""
    return dataset in CANON_DATASETS or is_archie_dynamic(dataset)
