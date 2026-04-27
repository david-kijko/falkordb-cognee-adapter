"""Safe Cypher interpolation primitives.

Only labels, relationship types, and property names that pass these validators may be
interpolated into Cypher. These helpers are for schema tokens only; all user data must
flow through FalkorDB ``$param`` parameters. No exceptions.
"""

from __future__ import annotations

import re

from fca.exceptions import FalkorSchemaError

LABEL_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
RELTYPE_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
PROPERTY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def safe_label(label: str) -> str:
    """Return label if it matches LABEL_RE; else raise FalkorSchemaError.

    Use ONLY for safe interpolation of node labels. NEVER use for user data.
    """
    if not isinstance(label, str) or LABEL_RE.fullmatch(label) is None:
        raise FalkorSchemaError(f"Unsafe Cypher label: {label!r}")
    return label


def safe_reltype(rel: str) -> str:
    """Return rel if it matches RELTYPE_RE; else raise FalkorSchemaError."""
    if not isinstance(rel, str) or RELTYPE_RE.fullmatch(rel) is None:
        raise FalkorSchemaError(f"Unsafe Cypher relationship type: {rel!r}")
    return rel


def safe_property_name(prop: str) -> str:
    """Return prop if it is safe for property interpolation; else raise FalkorSchemaError.

    Property names follow label-like rules but may start with a lower-case letter.
    """
    if not isinstance(prop, str) or PROPERTY_RE.fullmatch(prop) is None:
        raise FalkorSchemaError(f"Unsafe Cypher property name: {prop!r}")
    return prop
