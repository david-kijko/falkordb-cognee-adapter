from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

from fca.lessons import LessonsLog


def _append_many(path: str, worker: int, count: int) -> None:
    log = LessonsLog(path)
    for index in range(count):
        log.append_pending({"worker": worker, "index": index, "evidence_refs": []})


def test_concurrent_writers_see_no_torn_records(tmp_path: Path):
    path = tmp_path / "lessons.jsonl"
    workers = 6
    count = 25
    processes = [mp.Process(target=_append_many, args=(str(path), worker, count)) for worker in range(workers)]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)

    assert all(process.exitcode == 0 for process in processes)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == workers * count
    decoded = [json.loads(line) for line in lines]
    assert {row["status"] for row in decoded} == {"pending"}
    assert len({row["lesson_id"] for row in decoded}) == workers * count
    assert list(LessonsLog(path).pending_records())
