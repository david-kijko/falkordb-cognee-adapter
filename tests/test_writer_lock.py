"""Cross-process writer lock behavior."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fca.writer_lock import writer_lock


CODE = """
from pathlib import Path
from fca.writer_lock import WriterLockBusy, writer_lock
try:
    with writer_lock(Path(r'{path}'), timeout=1.0):
        pass
except WriterLockBusy:
    raise SystemExit(2)
raise SystemExit(0)
"""


def _attempt_lock(path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    return subprocess.run(
        [sys.executable, "-c", CODE.format(path=str(path))],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_writer_lock_blocks_contending_process_then_allows_fresh_acquire(tmp_path: Path) -> None:
    lock_path = tmp_path / "writer.lock"

    with writer_lock(lock_path, timeout=1.0):
        blocked = _attempt_lock(lock_path)

    acquired = _attempt_lock(lock_path)

    assert blocked.returncode == 2
    assert acquired.returncode == 0, acquired.stderr
