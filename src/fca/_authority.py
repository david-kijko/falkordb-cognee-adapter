"""Shared adapter authority guard helpers."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from fca.exceptions import ReadAuthorityError, WriteAuthorityError
from fca.roles import Role, can_read, can_write


def assert_can_read(role: Role, dataset: str) -> None:
    if not can_read(role, dataset):
        raise ReadAuthorityError(f"Role {role.value!r} cannot read dataset {dataset!r}")


def assert_can_write(role: Role, dataset: str) -> None:
    if not can_write(role, dataset):
        raise WriteAuthorityError(f"Role {role.value!r} cannot write dataset {dataset!r}")


def guarded_op(telemetry_op: Callable[[Callable[..., Any]], Callable[..., Any]], guard_name: str):
    """Build a telemetry-wrapped operation decorator that runs one adapter guard first."""

    def decorate(func):
        @telemetry_op
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            getattr(self, guard_name)(self.graph_name)
            return await func(self, *args, **kwargs)

        return wrapper

    return decorate
