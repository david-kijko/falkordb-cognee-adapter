#!/usr/bin/env python3
"""Replay pending Archie lesson WAL records mechanically.

Slice 4 intentionally does not call Cognee/FalkorDB. Replay validates the local
lesson payload shape and appends terminal tombstones for pending records old
enough to replay.
"""

from __future__ import annotations

import argparse
import fcntl
import importlib
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fca.lessons import LessonsLog, LessonRecord


class ReplayLockedError(RuntimeError):
    """Raised when another replay process holds the replay-wide lock."""


class ValidationFailure(ValueError):
    """Payload validation failure with a stable tombstone reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


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


def replay(
    path: Path,
    *,
    grace: float,
    dry_run: bool = False,
    provenance: Path | None = None,
    lesson_schema: str | None = None,
) -> int:
    with _replay_lock(path):
        log = LessonsLog(path)
        schema_model = _load_lesson_schema(lesson_schema) if lesson_schema else None
        provenance_store = _load_provenance_store(provenance) if provenance else None
        if provenance_store is None:
            print(
                "WARNING: --provenance not provided; evidence span existence is not checked; "
                "using shallow validation only",
                file=sys.stderr,
            )
        now = time.time()
        exit_code = 0
        for record in list(log.pending_records()):
            if now - record.created_at < grace:
                continue
            try:
                _validate_pending_record(record, schema_model=schema_model, provenance_store=provenance_store)
            except ValidationFailure as exc:
                if not dry_run:
                    log.mark_rejected(record.lesson_id, exc.reason)
                exit_code = 2
                continue
            except ValueError as exc:
                if not dry_run:
                    log.mark_rejected(record.lesson_id, str(exc))
                exit_code = 2
                continue
            if not dry_run:
                log.mark_graphed(record.lesson_id, "validated for Slice 4 mechanical replay")
        return exit_code


def _validate_pending_record(
    record: LessonRecord,
    *,
    schema_model: type[Any] | None = None,
    provenance_store: Any | None = None,
) -> None:
    if record.status != "pending":
        raise ValueError("only pending records can be replayed")
    if not record.lesson_id:
        raise ValueError("lesson_id is required")
    if not record.sha256:
        raise ValueError("sha256 is required")
    _validate_payload(record.payload)
    if schema_model is not None:
        try:
            schema_model.model_validate(record.payload)
        except Exception as exc:
            try:
                from pydantic import ValidationError as PydanticValidationError
            except ImportError:
                PydanticValidationError = ValueError  # type: ignore[assignment]
            if isinstance(exc, PydanticValidationError):
                raise ValidationFailure("schema_violation") from exc
            raise
    if provenance_store is not None:
        for ref in record.payload.get("evidence_refs") or []:
            if not provenance_store.exists(ref["span_id"]):
                raise ValidationFailure("missing_evidence_span_id")


def _load_lesson_schema(qualified_name: str) -> type[Any]:
    module_name, separator, class_name = qualified_name.rpartition(".")
    if not separator:
        raise ValueError("--lesson-schema must be MODULE.CLASS")
    model = getattr(importlib.import_module(module_name), class_name)
    try:
        from pydantic import BaseModel
    except ImportError as exc:
        raise ValueError("pydantic is required for --lesson-schema") from exc
    if not isinstance(model, type) or not issubclass(model, BaseModel):
        raise ValueError("--lesson-schema must point to a Pydantic BaseModel subclass")
    return model


def _load_provenance_store(path: Path) -> Any:
    from archie_canon_schema.provenance import SqliteProvenanceStore

    return SqliteProvenanceStore(path)


@contextmanager
def _replay_lock(path: Path):
    lock_path = path.with_name("lessons.replay.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        deadline = time.monotonic() + 5.0
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise ReplayLockedError("replay locked") from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--grace", type=float, default=60.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--lesson-schema")
    parser.add_argument("path")
    args = parser.parse_args(argv)

    path = Path(args.path)
    if not path.exists() or not path.is_file():
        print(f"invalid path: {path}", file=sys.stderr)
        return 1
    try:
        return replay(
            path,
            grace=args.grace,
            dry_run=args.dry_run,
            provenance=args.provenance,
            lesson_schema=args.lesson_schema,
        )
    except ReplayLockedError as exc:
        print(str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
