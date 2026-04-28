# Roles and Authority Matrices

Archie v0.1 uses coarse dataset-level roles. The adapter receives only `role`
and `dataset`; it does not yet receive an end-user principal or ownership row.
Dynamic `session_*` and `investigation_*` datasets are therefore readable by all
roles in v0.1 and writable only by Archie.

## Write matrix

| Role | May write fixed datasets | Dynamic datasets |
| --- | --- | --- |
| `ingestor` | `canon`, `exemplars`, `ingestion_metadata` | no |
| `validator` | `lessons`, `canon_errata` | no |
| `archie` | `quarantine` | `session_*`, `investigation_*` |

Source of truth: `src/fca/roles.py` `WRITE_MATRIX` plus `can_write()`.

## Read matrix

| Role | May read fixed datasets | Dynamic datasets |
| --- | --- | --- |
| `ingestor` | `canon`, `exemplars`, `ingestion_metadata` | yes |
| `validator` | `canon`, `exemplars`, `lessons`, `canon_errata`, `quarantine`, `ingestion_metadata` | yes |
| `archie` | `canon`, `exemplars`, `lessons`, `canon_errata`, `quarantine` | yes |

Source of truth: `src/fca/roles.py` `READ_MATRIX` plus `can_read()`.

## Rationale

The matrices separate duties by data lifecycle:

- Ingestors can write canonical source material, examples, and ingestion
  metadata, but cannot validate lessons or alter quarantine.
- Validators can write lesson outcomes and canon errata, but cannot rewrite the
  canon directly.
- Archie can write working-session and investigation graphs, plus quarantine,
  but not canonical ingestion metadata.

This is an authorization quality attribute in the sense of Bass, Clements, and
Kazman's *Software Architecture in Practice*, Chapter 21 on ATAM: access-control
policy is an architectural concern that must be evaluated as a concrete quality
attribute scenario, not left as incidental application logic.

The guard tests are also architecture fitness functions in the sense of Neal
Ford, Rebecca Parsons, and Patrick Kua's *Building Evolutionary Architectures*:
`tests/test_every_method_guarded.py` turns "every public adapter method calls a
guard before driver access" into an executable rule. When Cognee adds or changes
an abstract method, the introspection test fails until that method is assigned a
read or write guard.

## Enforcement points

- `src/fca/_authority.py` raises `ReadAuthorityError` or `WriteAuthorityError`.
- `src/fca/adapter.py` wraps every public method with `read_op` or `write_op`.
- `src/fca/router.py` checks write authority before dataset deletion.
- Telemetry records `read_authority` or `write_authority` in `failure_class` when
  a guard rejects a call.

## v0.2 tightening

When the adapter receives caller-principal context, dynamic dataset reads should
be narrowed from "all roles may read all dynamic datasets" to "callers may read
only dynamic datasets they own or are explicitly granted." The current matrix is
an intentional v0.1 approximation documented in `src/fca/roles.py`.
