# Storage Layer Maturity

Last updated: 2026-06-03

Status: Phase 1 complete. Later phases deferred.

## Goal

Make the storage layer reliable enough for production deployment without
changing the database engine or introducing heavy infrastructure dependencies.

This design is successful when:

- SQLite handles concurrent reads and writes without blocking.
- Schema changes are versioned, auditable, and safe to run on a live database.
- File artifacts are accessed through an abstraction layer that can be swapped
  for object storage later.
- A misconfigured deployment fails fast at startup instead
  of silently corrupting data or failing at runtime under load.

## Current State

| Concern | What we have today | Gap |
|---------|--------------------|-----|
| Database | SQLite via `aiosqlite`, single file at `./data/app.db`; WAL, busy timeout, `synchronous=NORMAL`, and foreign keys are configured on connections | Still a single-node database; no schema-version baseline yet |
| Schema migrations | Inline `ALTER TABLE` inside `init_db()` with try/except | No version tracking, no rollback, migrations are silently idempotent |
| File storage | Direct `pathlib`/`shutil` on local disk (`data/general_uploads`, `data/general_parsed`) | No abstraction layer; swapping to S3 means touching every service |
| Job queue | FastAPI `BackgroundTasks` + durable `jobs` table | No retry policy, no concurrency control, no dead-letter handling |
| Startup validation | Pydantic-settings reads `.env`; startup validates SQLite pragmas, directory writability, disk space, and Milvus policy | No full provider readiness suite or backup/restore validation |
| Observability | `query_run_stats`, `document_error_events`, `/health`, and storage/Milvus health payloads | No deep storage-layer metrics (DB wall time, lock contention, file I/O bytes, write errors) |

## Importance

This work is important, but it is not urgent feature work.

Storage maturity becomes P1 only when the project is preparing for a real
long-lived deployment, larger concurrent usage, or repeated schema/storage
changes. For the current feature-freeze/polish pass, it should stay planned and
deferred unless SQLite lock errors, filesystem permission issues, or migration
drift start blocking daily development.

Recommended priority:

```text
High value, low risk:
- SQLite pragmas and startup validation.

High value, medium risk:
- schema migration baseline for future changes.

Useful but larger:
- local file-storage abstraction for upload/parsed/image artifacts.

Deferred until needed:
- S3/object storage compatibility.
- rollback support.
- deep per-request storage metrics.
```

## Plan

The work is organized into four phases, each independently shippable.

---

### Phase 1 — SQLite hardening and startup guard

**Scope:** Make SQLite safe for concurrent production traffic without changing the
engine, and catch basic storage misconfiguration before serving traffic.

| # | Task | Detail |
|---|------|--------|
| 1.1 | Centralize connection setup | Keep short-lived `get_db()` connections, but route every new connection through one helper that applies required pragmas. Do not replace `get_db()` with a singleton connection. |
| 1.2 | Enable WAL journal mode | Set `PRAGMA journal_mode=WAL` during startup and validate the result. WAL allows concurrent readers while a writer is active. |
| 1.3 | Set busy timeout | `PRAGMA busy_timeout=5000` on every connection so writers retry for up to 5 s instead of failing immediately on lock contention. |
| 1.4 | Tune synchronous mode | `PRAGMA synchronous=NORMAL` — safe with WAL and significantly faster writes than FULL. |
| 1.5 | Enable foreign keys on connections | `PRAGMA foreign_keys=ON` on every connection. This prepares the runtime for future FK constraints, but does not create constraints by itself. |
| 1.6 | Startup pragma validation | On boot, log active pragmas: journal mode, busy timeout, foreign keys, synchronous. If WAL is not active after setting it, log a warning — the filesystem may not support it. |
| 1.7 | Directory writability check | On startup, attempt to create and delete a temp file in the database directory, `GENERAL_UPLOAD_DIR`, and `GENERAL_PARSED_DIR`. Fail with a clear message if not writable. |
| 1.8 | Disk space guard | On startup, check available disk space on the data volume. Warn if below a configurable threshold such as 1 GB. |
| 1.9 | Basic health payload | Add SQLite pragma status, data path writability, disk space, and Milvus reachability to `/health`. |

**Acceptance criteria:**

- All four pragmas are set on every new connection.
- Unit test verifies pragma values after `init_db()`.
- A load test with 10 concurrent readers + 1 writer shows zero `SQLITE_BUSY` errors.
- Removing write permission on `data/` causes startup to fail with a clear error.
- `/health` reports database and local storage status.

**Files changed:** `backend/app/core/database.py`, `backend/app/main.py`,
new `backend/app/core/health.py`, `backend/tests/unit/test_database_schema.py`

**Important implementation note:** keep multiple short-lived SQLite connections.
With WAL, readers and a writer can coexist. A single module-level `aiosqlite`
connection would serialize all operations and can create head-of-line blocking.

---

### Phase 2 — Versioned schema migration baseline

**Scope:** Add version tracking for future schema changes without trying to
retroactively rebuild the entire existing migration history in one pass.

| # | Task | Detail |
|---|------|--------|
| 2.1 | Create `schema_migrations` table | `(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)`. |
| 2.2 | Baseline current schema | Stamp the current known schema as a baseline version. Fresh databases are created from the current bootstrap schema and stamped; existing databases are inspected and stamped if compatible. |
| 2.3 | Future migration runner | Function `run_migrations(conn, migrations_dir)` reads SQL files ordered by version number, skips already-applied versions, and records each success. |
| 2.4 | Add future migrations only | New schema changes go into numbered SQL files under `backend/migrations/`. Do not first extract all historical inline `ALTER TABLE` blocks into retroactive migrations. |
| 2.5 | CLI command | `python -m app.migrate status` and `python -m app.migrate up`. |
| 2.6 | Foreign-key rebuild plan | If real FK constraints are added later, use explicit table-rebuild migrations. `PRAGMA foreign_keys=ON` alone does not add constraints to existing tables. |

**Acceptance criteria:**

- Fresh database: `init_db()` creates the current schema, stamps baseline, then runs future migrations.
- Existing database: `init_db()` detects compatibility, stamps baseline, and skips already-present columns.
- Migration history is queryable: `SELECT * FROM schema_migrations ORDER BY version`.
- Adding a new migration SQL file is the only step needed to evolve the schema.

**Files changed:** `backend/app/core/database.py`, new `backend/migrations/` directory, new `backend/app/core/migrate.py`

**Deferred:** rollback support. SQLite rollback migrations often require table
rebuilds and can create false confidence. Add rollback only after forward
migrations have proven useful.

**Compatibility rule for existing databases:** if `schema_migrations` does not
exist, inspect the current schema before stamping the baseline. At minimum, the
database must contain the required base tables used by the current app:
`general_documents`, `query_chat_messages`, `query_run_stats`, `users`,
`document_acl`, `query_feedback`, `jobs`, `entity_aliases`, and
`structured_tag_overrides`. For each table, verify the current required columns
exist before marking the baseline as applied.

---

### Phase 3 — Local file storage abstraction

**Scope:** Introduce a protocol for project-owned artifacts while keeping the
first implementation local-only.

| # | Task | Detail |
|---|------|--------|
| 3.1 | Define `FileStorage` protocol | `put_bytes(key, data) -> StorageRef`, `get_bytes(key) -> bytes`, `delete(key)`, `exists(key) -> bool`, `list_prefix(prefix) -> list[StorageRef]`. |
| 3.2 | Define `StorageRef` | Stable fields such as `key`, `uri`, `size`, `updated_at`, and optional `local_path`. Do not make local filesystem paths the API contract. |
| 3.3 | Implement `LocalFileStorage` | Wrap current `pathlib`/`shutil` calls. Key maps to `{base_dir}/{key}`. Add path traversal guards. |
| 3.4 | Add local materialization helper | Some parsers need real local paths. Provide `open_local(key)` or `materialize(key)` semantics so future object storage can stage temp files safely. |
| 3.5 | Migrate bounded call sites | Start with uploaded source files, parsed artifacts, chunk quality reports, and image assets. Leave unrelated files alone. |
| 3.6 | Integration test | Run document upload + parse pipeline with `LocalFileStorage`. Verify artifacts are stored and retrievable. |

**Acceptance criteria:**

- Uploads, parsed artifacts, image assets, and quality reports use `FileStorage`.
- Direct local `Path` usage remains allowed only where a third-party parser requires a temporary local path.
- Existing upload + parse tests pass unchanged.

**Files changed:** new `backend/app/core/file_storage.py`, `backend/app/services/document_*.py`, `backend/app/config.py`

**Deferred:** S3 compatibility. The current ingestion pipeline still has
local-path assumptions, especially around parsing, zip/image assets, and source
preview. Add object storage only after the local abstraction is stable.

**Bounded storage scope:** Phase 3 applies only to project-owned document
artifacts:

- uploads under `general_uploads/{document_id}/`
- parsed artifacts under `general_parsed/{document_id}/`
- chunk quality reports
- extracted image assets and image metadata

Excluded from Phase 3:

- SQLite database files
- Milvus data
- eval result JSONL/summary files
- logs
- `.env` or runtime configuration files
- temporary parser scratch files unless they are produced from a managed
  `StorageRef`

---

### Phase 4 — Object storage compatibility and storage observability

**Scope:** Add object-storage compatibility and deeper storage telemetry only
after the local abstractions and migration baseline have proven stable.

| # | Task | Detail |
|---|------|--------|
| 4.1 | Configurable Milvus startup policy | Probe `MILVUS_URI` at startup. Whether failure is warning or fatal should be controlled by `MILVUS_REQUIRED_ON_STARTUP`, not by the file storage backend. |
| 4.2 | `S3FileStorage` implementation | Add object storage support after `StorageRef` and local materialization semantics are stable. |
| 4.3 | Storage backend config | `STORAGE_BACKEND=local|s3`, `S3_BUCKET`, `S3_ENDPOINT_URL`, credentials, and temp staging directory. |
| 4.4 | Database health check | Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check`. Log warnings on issues. |
| 4.5 | Instrumented wrappers | Track DB wall time and file I/O bytes in DB/storage wrappers. Middleware can collect request-local counters, but cannot observe low-level I/O by itself. |
| 4.6 | Health and metrics endpoint | Add `schema_version`, `storage_backend`, storage health, and optional Prometheus-compatible metrics. |

**Acceptance criteria:**

- Switching `STORAGE_BACKEND=s3` redirects project-owned upload/parsed/image artifacts without changing service code.
- Parsers that need local paths work through temp materialization.
- `/health` returns `schema_version`, `storage_backend`, and storage health.
- Log output at startup includes migration version, storage backend, and Milvus status.

**Files changed:** `backend/app/main.py`, `backend/app/core/database.py`, new `backend/app/core/health.py`

---

## Out of scope

These are explicitly deferred to keep the plan focused:

- **Switching from SQLite to PostgreSQL.** WAL mode + busy timeout handles
  moderate production load. A migration to Postgres is a separate project with
  its own data migration plan.
- **Celery / Redis task queue.** The current FastAPI `BackgroundTasks` model
  works for single-process deployments. Horizontal scaling the worker layer is
  a different concern.
- **Encrypted storage at rest.** Depends on infrastructure (LUKS, S3 SSE).
  Not an application-layer concern in the current deployment model.
- **Historical rollback migration framework.** Add forward migrations first.
  Rollback support is a separate risk-managed migration policy.
- **Full object-storage migration in P1.** The ingestion pipeline still has
  local-path assumptions. S3 should follow the local storage abstraction, not
  drive it.

## Dependency graph

```
Phase 1 (SQLite hardening + startup guard)
  │
  ├── Phase 2 (Schema migration baseline) ── depends on Phase 1 for reliable DDL
  │
  └── Phase 3 (Local file storage abstraction)
        │
        └── Phase 4 (Object storage + deeper observability)
```

Phase 2 and Phase 3 can proceed in parallel after Phase 1 lands. Phase 4 should
wait until Phase 2 and Phase 3 are complete so that migration version and
storage abstraction are both available.

## Immediate Implementation Plan

Only Phase 1 is active for the next pass. The goal is to harden SQLite and local
startup checks without changing product behavior.

### Iteration 1: SQLite Pragmas

Status: implemented on 2026-06-03.

Work:

- Add a shared database connection setup helper.
- Keep short-lived `get_db()` connections.
- Apply `busy_timeout`, `foreign_keys`, and `synchronous` on every connection.
- Set and validate WAL mode during startup.
- Add tests for effective pragma values.

Exit criteria:

- Existing DB callers keep the same API.
- Startup logs the active SQLite pragmas.
- Unit tests verify pragmas on a new connection.

Validation:

- `PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/unit/test_database_schema.py`
- `MILVUS_URI=http://localhost:19530 PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/unit`

### Iteration 2: Startup Storage Guard

Status: implemented on 2026-06-03.

Work:

- Add a small health/storage helper.
- Check database directory, upload directory, and parsed directory writability.
- Check available disk space on the data volume.
- Fail startup with a clear message for unwritable required directories.

Exit criteria:

- Normal startup still works.
- A deliberately unwritable data directory fails before serving traffic.

Validation:

- `PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/unit/test_storage_health.py backend/tests/unit/test_database_schema.py`
- `MILVUS_URI=http://localhost:19530 PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/unit`

Note: the chmod-based unwritable-directory test is skipped on environments where
the current user can still write to read-only directories, such as root or
permission-insensitive mounted filesystems.

### Iteration 3: Health Payload And Milvus Policy

Status: implemented on 2026-06-03.

Work:

- Extend `/health` with database/storage status.
- Add Milvus reachability status.
- Add `MILVUS_REQUIRED_ON_STARTUP` so production can fail fast while development
  can remain warning-only.

Exit criteria:

- `/health` reports SQLite, local storage, disk, and Milvus status.
- Milvus startup behavior is controlled by config, not by storage backend.

Validation:

- `PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/unit/test_storage_health.py backend/tests/unit/test_database_schema.py`
- `MILVUS_URI=http://localhost:19530 PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/unit`

### Iteration 4: Validation And Closeout

Status: completed on 2026-06-03.

Work:

- Run backend unit tests.
- Restart backend.
- Check `/health`.
- Upload a Markdown document.
- Run one lightweight eval:
  - API/UI: retrieval-only mode with `limit=1`, `concurrency=1`
  - CLI equivalent: `python backend/scripts/eval_golden_set.py --mode retrieval_only --limit 1 --concurrency 1`
- Mark Phase 1 complete or record blockers.

Exit criteria:

- No regression in document processing or eval.
- No SQLite lock errors in the smoke path.
- Remaining phases stay deferred.

Validation completed:

- Rebuilt and restarted the backend Docker service.
- Verified `/health` returns:
  - `status=ok`
  - SQLite `journal_mode=wal`
  - SQLite `busy_timeout=5000`
  - writable database/upload/parsed directories
  - disk-space status
  - reachable Milvus status
- Uploaded `manual_test_assets/phase13/phase13_normal.md`.
- Processed the uploaded document to `completed` with `quality_status=good`.
- Deleted the smoke document after validation.
- Ran retrieval-only eval with `limit=1`, `concurrency=1`.
- Eval succeeded with `Hit@5=100%`, `Hit@10=100%`, and no failures.

Closeout:

- Phase 1 is complete.
- Phase 2 migration baseline remains deferred.
- Phase 3 local file-storage abstraction remains deferred.
- Phase 4 object storage and deeper observability remains deferred.
