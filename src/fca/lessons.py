"""Write-through JSONL WAL for Archie lessons."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

LessonStatus = Literal["pending", "graphed", "rejected"]


@dataclass(frozen=True)
class LessonRecord:
    lesson_id: str
    status: LessonStatus
    jsonl_offset: int
    sha256: str
    created_at: float
    payload: dict[str, Any]
    detail: str = ""


class LessonsLog:
    """Write-through, file-locked JSONL WAL for lesson graph writes."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def append_pending(self, payload: dict) -> LessonRecord:
        """Append and fsync a pending lesson record before caller writes the graph."""
        created_at = time.time()
        payload_hash = _payload_sha256(payload)
        entropy = f"{created_at}:{time.time_ns()}:{payload_hash}".encode("utf-8")
        lesson_id = hashlib.sha256(entropy).hexdigest()
        return self._append(
            lesson_id=lesson_id,
            status="pending",
            sha256=payload_hash,
            created_at=created_at,
            payload=dict(payload),
        )

    def mark_graphed(self, lesson_id: str, detail: str = "") -> None:
        """Append a graphed tombstone for lesson_id."""
        self._append(lesson_id=lesson_id, status="graphed", detail=detail)

    def mark_rejected(self, lesson_id: str, reason: str) -> None:
        """Append a rejected tombstone for lesson_id."""
        self._append(lesson_id=lesson_id, status="rejected", detail=reason)

    def pending_records(self) -> Iterator[LessonRecord]:
        """Yield pending rows with no later graphed/rejected tombstone."""
        latest_pending: dict[str, LessonRecord] = {}
        terminal: set[str] = set()
        for record in self._records():
            if record.status == "pending":
                latest_pending[record.lesson_id] = record
                terminal.discard(record.lesson_id)
            else:
                terminal.add(record.lesson_id)
        for lesson_id, record in latest_pending.items():
            if lesson_id not in terminal:
                yield record

    def _records(self) -> Iterator[LessonRecord]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
            try:
                for line in fh:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        row = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    try:
                        yield LessonRecord(
                            lesson_id=str(row["lesson_id"]),
                            status=row["status"],
                            jsonl_offset=int(row["jsonl_offset"]),
                            sha256=str(row.get("sha256", "")),
                            created_at=float(row["created_at"]),
                            payload=dict(row.get("payload") or {}),
                            detail=str(row.get("detail", "")),
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def _append(
        self,
        *,
        lesson_id: str,
        status: LessonStatus,
        sha256: str = "",
        created_at: float | None = None,
        payload: dict[str, Any] | None = None,
        detail: str = "",
    ) -> LessonRecord:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.seek(0, 2)
                offset = fh.tell()
                if offset > 0:
                    fh.seek(offset - 1)
                    if fh.read(1) != "\n":
                        fh.seek(0, 2)
                        fh.write("\n")
                        fh.flush()
                        os.fsync(fh.fileno())
                        offset = fh.tell()
                record = LessonRecord(
                    lesson_id=lesson_id,
                    status=status,
                    jsonl_offset=offset,
                    sha256=sha256,
                    created_at=time.time() if created_at is None else created_at,
                    payload={} if payload is None else payload,
                    detail=detail,
                )
                fh.write(json.dumps(record.__dict__, sort_keys=True, separators=(",", ":")) + "\n")
                fh.flush()
                fh.seek(0, 2)
                fh.truncate()
                os.fsync(fh.fileno())
                return record
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _payload_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()
