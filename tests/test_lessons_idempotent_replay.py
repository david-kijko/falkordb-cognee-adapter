from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fca.lessons import LessonsLog


def _run_replay(path: Path):
    return subprocess.run(
        [sys.executable, "scripts/replay_lessons.py", "--grace", "0", str(path)],
        check=False,
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )


def test_running_replay_twice_produces_same_state(tmp_path: Path):
    path = tmp_path / "lessons.jsonl"
    log = LessonsLog(path)
    first = log.append_pending({"claim": "one", "evidence_refs": []})
    second = log.append_pending({"claim": "two", "evidence_refs": [{"span_id": "s1"}]})

    result1 = _run_replay(path)
    after_first = path.read_text(encoding="utf-8")
    state_after_first = [(record.lesson_id, record.status) for record in LessonsLog(path)._records()]

    result2 = _run_replay(path)
    after_second = path.read_text(encoding="utf-8")
    state_after_second = [(record.lesson_id, record.status) for record in LessonsLog(path)._records()]

    assert result1.returncode == 0, result1.stderr
    assert result2.returncode == 0, result2.stderr
    assert after_second == after_first
    assert state_after_second == state_after_first
    assert list(LessonsLog(path).pending_records()) == []
    assert {(record.lesson_id, record.status) for record in LessonsLog(path)._records()} >= {
        (first.lesson_id, "graphed"),
        (second.lesson_id, "graphed"),
    }
