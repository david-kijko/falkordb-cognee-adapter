# Operations Runbook

This runbook covers local/prod FalkorDB operations for the adapter. Production
uses `docker-compose.yml` on `127.0.0.1:6379`; tests use
`docker-compose.test.yml` on `127.0.0.1:6380`. Never point fixture tests or
slice development at live `:6379`.

## Bootstrap a fresh FalkorDB instance

1. Set the production password and start FalkorDB:

   ```bash
   export FALKOR_PASSWORD='...'
   docker compose up -d falkordb
   ```

2. Verify the server responds:

   ```bash
   docker compose ps
   ```

3. Create or verify the six fixed Archie dataset markers:

   ```bash
   /home/david/.venvs/archie-1.0/bin/python scripts/bootstrap.py --create-roster
   ```

   The script creates `DatasetMeta` markers for `canon`, `exemplars`,
   `ingestion_metadata`, `lessons`, `canon_errata`, and `quarantine`. Use
   `--dry-run` to preview. Graph drops require owner markers, and fraud drops
   require both `--confirm-drop-fraud` and `--yes`.

## Ingest the canon

Canon ingestion is orchestrated outside this repository by the Archie system.
Use this adapter as the FalkorDB/Cognee persistence backend, route writes through
`DatasetRouter(role=Role.INGESTOR)`, and write canonical source data only into
`canon`, `exemplars`, and `ingestion_metadata`. Keep high-level ingestion
procedures in `archie-system`; this repo owns the adapter, guard, telemetry, and
backup behavior.

## Run `promote_lessons`

Slice 4 provides mechanical lesson WAL replay through `scripts/replay_lessons.py`.
Given a JSONL lessons WAL:

```bash
/home/david/.venvs/archie-1.0/bin/python scripts/replay_lessons.py \
  --grace 60 \
  --dry-run \
  /path/to/lessons.jsonl
```

Remove `--dry-run` to append terminal `graphed` or `rejected` tombstones. When
available, pass `--provenance /path/to/provenance.sqlite` and
`--lesson-schema package.module.LessonModel` so replay validates evidence spans
and lesson shape before promotion. The replay process uses a sibling
`lessons.replay.lock` file to prevent concurrent promotion.

## Back up graphs

Run the Slice 5 exporter against the datasets that must survive disaster
recovery:

```bash
/home/david/.venvs/archie-1.0/bin/python scripts/export_nightly.py \
  --datasets canon,exemplars,lessons,canon_errata \
  --output-root ./backups
```

Archives are compressed Cypher (`*.cypher.zst`) with adjacent manifest JSON,
sha256, node/edge counts, schema version, and exporter version. The exporter
skips `quarantine`, `ingestion_metadata`, `session_*`, and `investigation_*` by
default so transient or sensitive graphs are not accidentally retained.

## Restore from backup

Choose the archive and confirm the manifest exists. Restore requires explicit
permission to replace the target graph:

```bash
/home/david/.venvs/archie-1.0/bin/python scripts/restore_backup.py \
  --graph canon \
  --archive ./backups/canon/YYYY/MM/DD/HH.cypher.zst \
  --confirm-delete-target
```

The restore path verifies sha256, replays into a staging graph, checks restored
node/edge counts against the manifest, then swaps staging into the target. It
uses `/tmp/falkordb-cognee-adapter.<graph>.lock` to avoid concurrent restores.
If replay or count verification fails, the target graph is left untouched.

## Monitor telemetry

Use `StdlibSink` for production adapter telemetry:

```python
from pathlib import Path
from fca.telemetry import StdlibSink

telemetry = StdlibSink(path=Path('/var/log/archie/fca.jsonl'), fsync_each=False)
```

Each adapter operation writes one JSON line with `op`, `dataset`, `role`,
`latency_ms`, `rows_in`, `rows_out`, `retries`, `failure_class`,
`schema_version`, and `ts`. Set `fsync_each=True` only when crash-safe telemetry
is worth the per-operation disk-sync cost. For normal service logs, rely on the
file handle flush plus host log shipping.

Useful checks:

```bash
# Recent failures by class
jq -r 'select(.failure_class != null) | [.ts,.dataset,.op,.failure_class] | @tsv' /var/log/archie/fca.jsonl | tail

# Slow operations over one second
jq 'select(.latency_ms >= 1000)' /var/log/archie/fca.jsonl
```

## Common `failure_class` meanings and fixes

| failure_class | Meaning | First fix |
| --- | --- | --- |
| `connection` | FalkorDB/Redis connection refused or lost | Check container health, host/port, password, network binding. |
| `timeout` | Socket/connect timeout | Check FalkorDB load, long queries, network latency, timeout settings. |
| `query` | FalkorDB rejected Cypher or adapter payload unsupported | Inspect `op`, inputs, and FalkorDB error; add/repair adapter query tests. |
| `schema` | Unsafe label/property/relationship or invalid vector collection/depth | Sanitize names; keep user data in params, not interpolated identifiers. |
| `embedding` | Missing vector collection, dimension mismatch, or embedding failure | Verify collection creation, embedding backend, model dimensions, and query vector length. |
| `read_authority` | Role cannot read the dataset | Use the right role/dataset route; check `READ_MATRIX`. |
| `write_authority` | Role cannot write/delete the dataset | Use the right role/dataset route; check `WRITE_MATRIX`. |
| `query_guard` | Read-mode query contains write/index-create tokens | Route writes through write methods or remove unsafe Cypher from reads. |
| `cognee_contract_drift` | Installed Cognee API differs from frozen contract | Follow `docs/UPGRADE_PROCEDURE.md` before bumping the pin. |
