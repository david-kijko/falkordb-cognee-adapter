"""Typed exceptions emitted by the FalkorDB Cognee adapter."""

from __future__ import annotations

from typing import ClassVar


class FalkorAdapterError(Exception):
    """Base for all adapter-emitted errors. Always carries failure_class."""

    failure_class: ClassVar[str] = "unknown"


class FalkorConnectionError(FalkorAdapterError):
    failure_class: ClassVar[str] = "connection"


class FalkorQueryError(FalkorAdapterError):
    failure_class: ClassVar[str] = "query"


class FalkorSchemaError(FalkorAdapterError):
    """Raised by safe_label/safe_reltype/safe_property_name."""

    failure_class: ClassVar[str] = "schema"


class FalkorTimeoutError(FalkorAdapterError):
    failure_class: ClassVar[str] = "timeout"


class FalkorEmbeddingError(FalkorAdapterError):
    failure_class: ClassVar[str] = "embedding"


class CogneeContractError(FalkorAdapterError):
    """Raised by upgrade contract test if installed Cognee drifts from frozen fixture."""

    failure_class: ClassVar[str] = "cognee_contract_drift"


class ReadAuthorityError(FalkorAdapterError):
    failure_class: ClassVar[str] = "read_authority"


class WriteAuthorityError(FalkorAdapterError):
    failure_class: ClassVar[str] = "write_authority"


class QueryGuardError(FalkorAdapterError):
    failure_class: ClassVar[str] = "query_guard"
