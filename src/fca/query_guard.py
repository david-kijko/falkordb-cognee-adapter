"""v0.1 conservative regex policy for Cypher read safety.

False positives are acceptable; false negatives are not. This is not a Cypher
parser: read-mode queries are rejected when regexes find write tokens or
FalkorDB index-create procedure calls in any context, including string literals,
comments, and identifiers. Slice 7 considers a proper Cypher parser.
"""

from __future__ import annotations

import re
from enum import Enum

from fca.exceptions import QueryGuardError

WRITE_TOKENS = re.compile(r"\b(CREATE|MERGE|SET|DELETE|DROP|REMOVE)\b", re.IGNORECASE)
WRITE_TOKEN_PREFIXES = re.compile(r"\b(Create|Merge|Set|Delete|Drop|Remove)")
INDEX_CREATE = re.compile(r"\bCALL\s+db\.idx\.[a-z_]+\.create", re.IGNORECASE)


class QueryMode(str, Enum):
    READ = "read"
    WRITE = "write"


def assert_read_safe(cypher: str) -> None:
    """Raise QueryGuardError if read-mode Cypher regex-matches write syntax.

    v0.1 intentionally does not parse Cypher context. Any matching write token,
    including in strings, comments, or identifiers, is rejected.
    """
    if INDEX_CREATE.search(cypher) or WRITE_TOKENS.search(cypher) or WRITE_TOKEN_PREFIXES.search(cypher):
        raise QueryGuardError("Read-mode query contains write or index-create token")
