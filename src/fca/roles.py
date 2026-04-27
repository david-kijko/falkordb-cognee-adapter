"""Bare role enum for Slice 1.

Slice 2 fills:
- WRITE_MATRIX / READ_MATRIX
- can_write / can_read helpers
- adapter/router role guards
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    INGESTOR = "ingestor"
    VALIDATOR = "validator"
    ARCHIE = "archie"
