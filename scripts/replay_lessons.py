#!/usr/bin/env python3
"""Replay pending Archie lesson WAL records mechanically.

Slice 4 intentionally does not call Cognee/FalkorDB. Replay validates the local
lesson payload shape and appends terminal tombstones for pending records old
enough to replay.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from fca.lessons import LessonsLog, LessonRecord


def _validate_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    evidence_refs = payload.get("evidence_refs", [])
    if evidence_refs is None:
        evidence_refs = []
    if not isinstance(evidence_refs, list):
        raise ValueError("evidence_refs must be a list when present")
    for index, ref in enumerate(evidence_refs):
        if not isinstance(ref, dict):
            raise ValueError(f"evidence_refs[{index}] must be an object")
        span_id = ref.get("span_id")
        if not isinstance(span_id, str) or not span_id:
            raise ValueError(f"evidence_refs[{index}].span_id is required")


def replay(path: Path, *, grace: float, dry_run: bool = False) -> int:
    log = LessonsLog(path)
    now = time.time()
    exit_code = 0
    for record in list(log.pending_records()):
        if now - record.created_at < grace:
            continue
        try:
            _validate_pending_record(record)
        except ValueError as exc:
            if not dry_run:
                log.mark_rejected(record.lesson_id, str(exc))
            exit_code = 2
            continue
        if not dry_run:
            log.mark_graphed(record.lesson_id, "validated for Slice 4 mechanical replay")
    return exit_code


def _validate_pending_record(record: LessonRecord) -> None:
    if record.status != "pending":
        raise ValueError("only pending records can be replayed")
    if not record.lesson_id:
        raise ValueError("lesson_id is required")
    if not record.sha256:
        raise ValueError("sha256 is required")
    _validate_payload(record.payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--grace", type=float, default=60.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("path")
    args = parser.parse_args(argv)

    path = Path(args.path)
    if not path.exists() or not path.is_file():
        print(f"invalid path: {path}", file=sys.stderr)
        return 1
    return replay(path, grace=args.grace, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
