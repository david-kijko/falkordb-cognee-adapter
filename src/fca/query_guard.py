"""Regex-only Cypher read safety guard.

This v0.1 guard is intentionally conservative and is not a Cypher parser. It
masks simple quoted string literals, then rejects read-mode queries containing
write tokens or FalkorDB index-create procedure calls. Comments are not parsed
as executable/non-executable regions, so write tokens in comments may be
rejected. That false-positive bias is deliberate for read-mode safety.
"""

from __future__ import annotations

import re
from enum import Enum

from fca.exceptions import QueryGuardError

WRITE_TOKENS = re.compile(r"\b(CREATE|MERGE|SET|DELETE|DROP|REMOVE)\b", re.IGNORECASE)
INDEX_CREATE = re.compile(r"\bCALL\s+db\.idx\.[a-z_]+\.create", re.IGNORECASE)
STRING_LITERAL = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"")


class QueryMode(str, Enum):
    READ = "read"
    WRITE = "write"


def _mask_string_literals(cypher: str) -> str:
    return STRING_LITERAL.sub(lambda match: " " * (match.end() - match.start()), cypher)


def assert_read_safe(cypher: str) -> None:
    """Raise QueryGuardError if read-mode Cypher appears to write.

    Approximation: v0.1 uses regexes after masking simple string literals, not a
    full Cypher parser. Anything outside a quoted literal matching write tokens
    or db.idx.*.create is rejected, including conservative comment false
    positives.
    """
    masked = _mask_string_literals(cypher)
    if INDEX_CREATE.search(masked) or WRITE_TOKENS.search(masked):
        raise QueryGuardError("Read-mode query contains write or index-create token")
