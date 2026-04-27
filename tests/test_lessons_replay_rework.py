from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from fca.lessons import LessonsLog


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_replay(path: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, "scripts/replay_lessons.py", *args, str(path)],
        check=False,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env=merged_env,
    )


def _terminal_row(path: Path, lesson_id: str) -> dict:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return [row for row in rows if row["lesson_id"] == lesson_id][-1]


def test_replay_rejects_missing_evidence_span(tmp_path: Path):
    fake_pkg = tmp_path / "fakepkg"
    package = fake_pkg / "archie_canon_schema"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "provenance.py").write_text(
        """
class SqliteProvenanceStore:
    def __init__(self, path):
        self.path = path

    def exists(self, span_id):
        return False
""",
        encoding="utf-8",
    )
    path = tmp_path / "lessons.jsonl"
    pending = LessonsLog(path).append_pending(
        {"claim": "needs evidence", "evidence_refs": [{"span_id": "missing"}]}
    )

    result = _run_replay(
        path,
        "--grace",
        "0",
        "--provenance",
        str(tmp_path / "provenance.sqlite"),
        env={"PYTHONPATH": f"{fake_pkg}:{REPO_ROOT / 'src'}"},
    )

    assert result.returncode == 2
    terminal = _terminal_row(path, pending.lesson_id)
    assert terminal["status"] == "rejected"
    assert terminal["detail"] == "missing_evidence_span_id"


def test_replay_with_pluggable_schema_rejects_invalid_payload(tmp_path: Path):
    module_dir = tmp_path / "schema"
    module_dir.mkdir()
    (module_dir / "sample_schema.py").write_text(
        """
from pydantic import BaseModel

class RequiresFoo(BaseModel):
    foo: int
""",
        encoding="utf-8",
    )
    path = tmp_path / "lessons.jsonl"
    pending = LessonsLog(path).append_pending({"claim": "no foo", "evidence_refs": []})

    result = _run_replay(
        path,
        "--grace",
        "0",
        "--lesson-schema",
        "sample_schema.RequiresFoo",
        env={"PYTHONPATH": f"{module_dir}:{REPO_ROOT / 'src'}"},
    )

    assert result.returncode == 2
    terminal = _terminal_row(path, pending.lesson_id)
    assert terminal["status"] == "rejected"
    assert terminal["detail"] == "schema_violation"


def test_concurrent_replayers_do_not_duplicate_tombstones(tmp_path: Path):
    module_dir = tmp_path / "schema"
    module_dir.mkdir()
    (module_dir / "slow_schema.py").write_text(
        """
import time
from pydantic import BaseModel

class SlowLesson(BaseModel):
    claim: str

    @classmethod
    def model_validate(cls, obj, *args, **kwargs):
        time.sleep(6)
        return super().model_validate(obj, *args, **kwargs)
""",
        encoding="utf-8",
    )
    path = tmp_path / "lessons.jsonl"
    pending = LessonsLog(path).append_pending({"claim": "one replay", "evidence_refs": []})
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{module_dir}:{REPO_ROOT / 'src'}"
    command = [
        sys.executable,
        "scripts/replay_lessons.py",
        "--grace",
        "0",
        "--lesson-schema",
        "slow_schema.SlowLesson",
        str(path),
    ]

    first = subprocess.Popen(command, cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    time.sleep(0.5)
    second = subprocess.Popen(command, cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    first_out, first_err = first.communicate(timeout=15)
    second_out, second_err = second.communicate(timeout=15)

    returncodes = sorted([first.returncode, second.returncode])
    assert returncodes == [0, 3], (first_out, first_err, second_out, second_err)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    tombstones = [
        row for row in rows if row["lesson_id"] == pending.lesson_id and row["status"] in {"graphed", "rejected"}
    ]
    assert len(tombstones) == 1
    assert "replay locked" in f"{first_err}\n{second_err}"


def test_pending_records_warns_on_torn_jsonl(tmp_path: Path, capsys):
    path = tmp_path / "lessons.jsonl"
    log = LessonsLog(path)
    log.append_pending({"claim": "good", "evidence_refs": []})
    torn_offset = path.stat().st_size
    with path.open("ab") as fh:
        fh.write(b'{"lesson_id": "torn", "status":')

    pending = list(log.pending_records())

    assert len(pending) == 1
    assert pending[0].payload["claim"] == "good"
    stderr = capsys.readouterr().err
    assert "WARNING" in stderr
    assert f"torn_record_at_offset={torn_offset}" in stderr


def test_replay_grace_keeps_fresh_records_pending(tmp_path: Path):
    path = tmp_path / "lessons.jsonl"
    pending = LessonsLog(path).append_pending({"claim": "fresh", "evidence_refs": []})

    result = _run_replay(path, "--grace", "300")

    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows == [rows[0]]
    assert rows[0]["lesson_id"] == pending.lesson_id
    assert rows[0]["status"] == "pending"
    assert [record.lesson_id for record in LessonsLog(path).pending_records()] == [pending.lesson_id]


def test_replay_dry_run_writes_no_tombstone(tmp_path: Path):
    path = tmp_path / "lessons.jsonl"
    LessonsLog(path).append_pending({"claim": "dry", "evidence_refs": []})
    before = path.read_bytes()

    result = _run_replay(path, "--grace", "0", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert path.read_bytes() == before


def test_replay_invalid_path_exits_1(tmp_path: Path):
    result = _run_replay(tmp_path / "missing.jsonl")

    assert result.returncode == 1
    assert "invalid path" in result.stderr
