"""Cross-process advisory writer lock for FalkorDB graph writers."""

from __future__ import annotations

import fcntl
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class WriterLockBusy(Exception):
    """Raised when a writer-lock cannot be acquired."""


@contextmanager
def writer_lock(
    lockfile_path: Path | str,
    timeout: float = 5.0,
    wait_message: str = "another writer holds the lock",
) -> Iterator[None]:
    """Cross-process advisory lock. Used by restore + ingest to coordinate.

    Acquires fcntl.LOCK_EX | LOCK_NB; retries every 0.1s until timeout.
    Raises WriterLockBusy on timeout.
    """
    lockfile_path = Path(lockfile_path)
    lockfile_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lockfile_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise WriterLockBusy(f"{wait_message}: {lockfile_path}") from exc
                time.sleep(0.1)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
