from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fca.lessons import LessonsLog


def test_crash_mid_write_replay_recovers_valid_pending_record(tmp_path: Path):
    path = tmp_path / "lessons.jsonl"
    log = LessonsLog(path)
    pending = log.append_pending({"claim": "recover me", "evidence_refs": []})

    with path.open("ab") as fh:
        fh.write(b'{"lesson_id": "torn", "status":')

    result = subprocess.run(
        [sys.executable, "scripts/replay_lessons.py", "--grace", "0", str(path)],
        check=False,
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert list(LessonsLog(path).pending_records()) == []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("{") and line.endswith("}")]
    assert any(row["lesson_id"] == pending.lesson_id and row["status"] == "graphed" for row in rows)


def test_replay_rejects_schema_invalid_pending_payload(tmp_path: Path):
    path = tmp_path / "lessons.jsonl"
    log = LessonsLog(path)
    pending = log.append_pending({"claim": "bad", "evidence_refs": [{"source_id": "s"}]})

    result = subprocess.run(
        [sys.executable, "scripts/replay_lessons.py", "--grace", "0", str(path)],
        check=False,
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    terminal = [record for record in LessonsLog(path)._records() if record.lesson_id == pending.lesson_id][-1]
    assert terminal.status == "rejected"
    assert "span_id" in terminal.detail
