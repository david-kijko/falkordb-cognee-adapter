# Architecture

`falkordb-cognee-adapter` is Archie's Cognee-facing persistence boundary. It
ports Cognee's graph and vector database interfaces onto FalkorDB while enforcing
Archie's dataset isolation, role authority, query safety, and telemetry
invariants.

## Layer diagram

```text
Caller / Archie workflow
        |
        v
DatasetRouter  (logical dataset -> one graph-bound adapter)
        |
        v
FalkorCogneeAdapter  (Cognee GraphDBInterface + VectorDBInterface)
        |
        v
FalkorSession / VectorIndexManager / Cypher builders
        |
        v
FalkorDB graph + vector indexes
```

The caller should route by logical dataset (`canon`, `lessons`, `session_*`, and
so on), not by raw graph name. `DatasetRouter` applies the isolation strategy and
constructs a `FalkorCogneeAdapter` bound to exactly one graph. The adapter then
implements Cognee's public graph/vector methods against that graph.

## Module map

- `src/fca/router.py` maps logical dataset names to cached adapter instances and
  owns dataset-level deletes.
- `src/fca/adapter.py` implements Cognee graph/vector interfaces, wraps every
  public operation with authority guards and telemetry, and delegates low-level
  work to helper modules.
- `src/fca/_authority.py` contains the guard decorator wiring. Guards execute
  before any driver call and are inside the telemetry wrapper so failures emit
  exactly one event.
- `src/fca/roles.py` defines `Role`, `WRITE_MATRIX`, `READ_MATRIX`, and the
  `can_read`/`can_write` policy functions.
- `src/fca/datasets.py` defines the six fixed Archie datasets plus dynamic
  `session_` and `investigation_` prefixes.
- `src/fca/isolation.py` maps dataset names to FalkorDB graph names and performs
  graph deletion for the graph-per-dataset strategy.
- `src/fca/_falkor_session.py` translates raw FalkorDB/Redis failures into typed
  adapter exceptions.
- `src/fca/_cypher_builders.py` and `src/fca/cypher.py` build Cypher and validate
  interpolated labels, relationship types, and property names.
- `src/fca/query_guard.py` enforces conservative read-mode Cypher safety before
  `query` reaches FalkorDB.
- `src/fca/_vector_index.py` owns FalkorDB vector-index naming, dimension checks,
  vector upserts, retrieval, and cleanup.
- `src/fca/embeddings.py` integrates the embedding backend used by vector search
  and data-point creation.
- `src/fca/lessons.py` implements the write-through JSONL WAL for lesson replay.
- `src/fca/telemetry.py` defines `TelemetrySink`, `NullSink`, and `StdlibSink`.
  `StdlibSink` writes one JSON line per adapter event to stderr or an append-only
  file.
- `src/fca/exceptions.py` defines the typed exception taxonomy and stable
  `failure_class` values emitted in telemetry.
- `scripts/bootstrap.py`, `scripts/export_nightly.py`, `scripts/restore_backup.py`,
  and `scripts/replay_lessons.py` provide operational bootstrap, backup, restore,
  and lesson replay entrypoints.

## Key invariants

### SP1: one graph per adapter

A `FalkorCogneeAdapter` instance is bound to one `graph_name` for its lifetime.
Cross-dataset routing belongs in `DatasetRouter`, not in adapter methods. This
keeps operation telemetry unambiguous: `event["dataset"]` is always the adapter's
current graph/dataset binding.

### SP2: every operation is guarded

Every public Cognee graph/vector interface method is decorated with either
`read_op` or `write_op`. The guard runs before FalkorDB driver access. The test
`tests/test_every_method_guarded.py` introspects Cognee's abstract interface
methods and verifies every public method calls exactly one guard before any fake
driver event.

### SP6: every operation is telemetry'd

The same public method surface emits telemetry through the adapter's configured
`TelemetrySink`. Success paths and failure paths emit exactly one event with
`op`, `dataset`, `role`, `latency_ms`, `rows_in`, `rows_out`, `retries`,
`failure_class`, `schema_version`, and `ts`. `NullSink` is the default so callers
can ignore telemetry; production callers can pass `StdlibSink` for JSON-lines
logs without changing adapter behavior.

## Failure model

Driver failures are translated in `FalkorSession.translate`, schema/query guard
failures are raised before unsafe Cypher reaches FalkorDB, and authority failures
are raised before any driver call. Telemetry preserves that distinction through
stable `failure_class` values, allowing operators to distinguish connection,
timeout, query, schema, embedding, authority, guard, and Cognee contract-drift
failures without parsing exception messages.
