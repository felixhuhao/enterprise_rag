# Phase 14: Background Job Reliability

Last updated: 2026-06-03

Status: P1 in progress. Iterations 1-3 implemented.

## Goal

Make long-running operations visible, diagnosable, and eventually retryable.

Phase 14 is successful when an admin can answer:

- What long-running work is running now?
- Which resource is it working on?
- How far did it get?
- Why did it fail?
- Can it be retried without corrupting document status, parsed artifacts, or
  Milvus vectors?

This phase is reliability infrastructure. It should not introduce a new queue
product, Celery/RQ dependency, or a broad workflow engine.

## Current Baseline

The project already has several long-running paths:

- Document processing uses FastAPI `BackgroundTasks`.
- Document retry performs Milvus cleanup and then starts another background
  processing task.
- Document delete/repair can touch Milvus, parsed artifacts, SQLite, and ACLs.
- Golden-set evaluation runs in a module-level thread with an in-memory `_state`.
- Phase 13 added processing history artifacts, but not durable job records.

Current gaps:

- A process restart loses active eval progress.
- Document processing status is visible, but the task itself is not represented
  as a first-class record.
- Evaluation and document processing use unrelated progress models.
- Failures are partly visible through document error events, but not through a
  shared job status API.
- Retry/cancel semantics are not consistently modeled.

## Scope Boundary

In scope:

- A durable `jobs` table.
- Shared job status service APIs.
- Admin job list/detail endpoints.
- Startup recovery for stale `running` jobs.
- Document ingestion jobs.
- Golden-set evaluation jobs.
- Job progress updates for existing long-running flows.
- Clear retry boundaries for document processing and eval.

Out of scope:

- Celery, RQ, Redis queue, or external worker deployment.
- Distributed worker orchestration.
- Scheduled/nightly jobs.
- Full job dependency DAGs.
- Long-term audit retention policy.
- Reparse/reindex UI in the first iteration.
- Canceling unsafe operations mid-Milvus write.

## P1 Scope

P1 is the minimum reliable job loop: create durable job records, expose them to
admins, and attach the two most important long-running paths.

### P1 Design Decisions

Progress semantics:

- Evaluation jobs use exact numeric progress:
  - `progress_total` = selected case count
  - `progress_current` = finished case count
- Document ingestion jobs use coarse stage progress, not chunk-level progress:
  - `progress_total` = fixed stage count
  - `progress_current` = latest completed/entered stage index
  - `message` = source-of-truth current stage label
- Document progress is not an ETA and not a true work ratio. Parsing, embedding,
  and saving can have very different runtimes. The UI should treat the
  percentage as a rough stage indicator and show `message` prominently.
- Do not attempt chunk-level progress in P1. Chunk count is unknown until after
  chunking, and embedding/indexing progress would require deeper batch hooks.

Suggested document stage mapping for P1:

```text
0 / 7 queued
1 / 7 processing
2 / 7 reading | parsing
3 / 7 normalizing
4 / 7 chunking
5 / 7 enriching
6 / 7 embedding
7 / 7 saving | completed
```

`created_by` semantics:

- Store the stable `user_id`, not username.
- Username can change or be localized; `user_id` is the durable audit key.
- API/UI can resolve `user_id` to username separately when needed.

`queued` semantics:

- P1 still creates jobs in `queued` first even though FastAPI `BackgroundTasks`
  usually starts them immediately.
- This keeps the state model honest for the short gap between API response and
  task start.
- If the process dies after job creation but before the background task starts,
  the job remains diagnosable instead of disappearing.
- The status also keeps the schema ready for a future worker without changing
  API contracts.

Frontend placement:

- Prefer a small global recent-jobs panel in the admin/settings area.
- Add contextual links/chips later from document detail and eval panels when a
  job is related to the current resource.
- Avoid making the Documents page a job dashboard; document pages should show
  document-relevant jobs only.

### P1.1 Job Schema And Service

Add a `jobs` table with stable fields:

```text
job_id
job_type
status               queued | running | succeeded | failed | canceled
resource_type        document | eval | cleanup | index
resource_id
progress_current
progress_total
message
error_code
error_detail
attempt_count
created_by
created_at
started_at
finished_at
updated_at
```

Required service behavior:

- Create a queued job.
- Mark job running.
- Update progress and message.
- Mark succeeded.
- Mark failed with `error_code` and `error_detail`.
- List recent jobs.
- Read one job by id.
- Mark stale `running` jobs as failed on startup.

P1 does not need a general worker loop. The service can be called by existing
FastAPI background tasks and eval threads.

### P1.2 Admin Job API

Add admin-only endpoints:

```text
GET /api/admin/jobs
GET /api/admin/jobs/{job_id}
```

Minimum response fields:

- all schema fields
- normalized status label
- progress percentage when `progress_total > 0`

Filtering:

- `status`
- `job_type`
- `resource_type`
- `resource_id`
- `limit`

No mutation endpoint is required in P1.1/P1.2.

### P1.3 Document Ingestion Job Integration

Wrap existing document processing and retry endpoints with job creation.

Required behavior:

- `/documents/{document_id}/process` returns `job_id`.
- `/documents/{document_id}/retry` returns `job_id`.
- Document status still moves through the existing ingestion statuses.
- Job progress mirrors ingestion status updates:
  - queued
  - processing
  - parsing
  - normalizing
  - chunking
  - embedding
  - indexing
  - completed / failed
- Job failure and document failure do not contradict each other.
- Retry cleanup failure records a failed job or a clear pre-job error, but does
  not start processing.

Important constraint:

- Do not add completed-document reparse/reindex in this iteration. Keep retry
  limited to failed documents until the job model proves stable.

### P1.4 Evaluation Job Integration

Attach golden-set eval runs to the job table.

Required behavior:

- `/admin/eval/run` returns `job_id`.
- Existing `/admin/eval/status` continues to work.
- Job progress mirrors case completion count.
- Job detail includes result and summary paths in the message or metadata path
  once available.
- Eval failure marks the job failed with a useful error message.
- Startup stale job recovery handles interrupted eval jobs.

Important constraint:

- Do not delete the existing `_state` path immediately. Bridge it to jobs first,
  then simplify after manual testing.

### P1.5 Lightweight Frontend Visibility

Expose recent jobs in the admin UI without creating a big dashboard.

Minimum UI:

- recent job list
- status chips
- job type/resource
- progress
- started/finished time
- error message preview
- detail drawer

Good candidate placement:

- Documents page for document jobs, or
- Settings/Admin area for global recent jobs

Do not block backend closeout on elaborate frontend controls.

## P2 Scope

P2 should start only after P1 proves stable under manual upload, retry, delete,
and eval runs.

### P2.1 Explicit Retry Endpoint

Add:

```text
POST /api/admin/jobs/{job_id}/retry
```

Rules:

- Retry only supported job types.
- Retry creates a new job record linked to the previous one, or increments
  `attempt_count` with clear history.
- Document processing retry must cleanup old vectors before reindexing.
- Eval retry can rerun the same request parameters if they were persisted.

### P2.2 Safe Cancel

Add:

```text
POST /api/admin/jobs/{job_id}/cancel
```

Only support safe cancellation:

- queued jobs
- eval runs between cases if the runner checks a cancellation flag
- document jobs only before irreversible Milvus/index writes

Do not fake cancellation for work that cannot safely stop.

### P2.3 Completed Document Reparse/Reindex

Add explicit reparse/reindex after job reliability exists.

Requirements:

- job-backed endpoint
- idempotent Milvus cleanup before inserting new vectors
- parsed artifact overwrite rules
- processing history append
- chunk-shape diff from Phase 13 P2.1 if useful

### P2.4 Cleanup Jobs

Represent delete and repair-delete as jobs if manual testing shows they are slow
or failure-prone.

Minimum:

- document delete job status
- cleanup stage messages
- partial cleanup diagnosis

### P2.5 Worker Extraction Readiness

Prepare the service boundary so a future worker can replace in-process tasks.

Do not implement an external worker unless the current process model is proven
insufficient.

## Not Doing In Phase 14

- No external queue service.
- No distributed workers.
- No job scheduling UI.
- No recurring eval runs.
- No full audit export.
- No arbitrary user-defined workflows.
- No completed-document reparse in P1.
- No unsafe cancel semantics.

## Implementation Iterations

### Iteration 1: Job Table, Service, And Read API

Status: implemented on 2026-06-03.

Purpose: create durable job records without changing existing long-running
endpoint behavior.

Work:

- Add `jobs` schema and migrations.
- Add job service helper functions.
- Add admin read endpoints.
- Add startup stale-running recovery.
- Add backend tests for schema, service lifecycle, and API shape.

Likely files:

- `backend/app/core/database.py`
- `backend/app/services/job_service.py`
- `backend/app/api/admin_jobs.py`
- `backend/app/api/router.py`
- `backend/app/main.py`
- `backend/tests/unit/test_jobs.py`
- `backend/tests/unit/test_database_schema.py`

Exit criteria:

- Jobs can be created, updated, listed, and read.
- Stale running jobs are marked failed on startup.
- No document/eval endpoint behavior changes yet.

Engineering validation:

- `backend/tests/unit/test_jobs.py`
- `backend/tests/unit/test_database_schema.py`

### Iteration 2: Document Processing Job Integration

Status: implemented on 2026-06-03.

Purpose: make upload/process/retry document work visible as jobs.

Work:

- Create job when document process/retry starts.
- Return `job_id` from process/retry endpoints.
- Pass `job_id` into `process_document`.
- Mirror ingestion status updates into coarse stage progress and job messages.
- Mark job succeeded/failed alongside document status.
- Add tests for success, failure, and retry cleanup failure.

Exit criteria:

- Manual upload shows a document job.
- Failed document processing has a failed job with error code/detail.
- Existing document status behavior remains correct.

Engineering validation:

- `backend/tests/unit/test_document_job_api.py`
- `backend/tests/unit/test_retry_safety.py`
- `backend/tests/unit/test_jobs.py`

### Iteration 3: Eval Job Integration

Status: implemented on 2026-06-03.

Purpose: make golden-set eval runs durable and diagnosable.

Work:

- Create eval job when `/admin/eval/run` starts.
- Return `job_id`.
- Store eval mode/flavor/limit context in message or a compact metadata field if
  one is added.
- Update progress from `_update_eval_progress`.
- Mark succeeded/failed in `_runner`.
- Keep `/admin/eval/status` behavior unchanged during the transition.

Exit criteria:

- Manual eval run appears in job list.
- Job progress matches completed case count.
- Eval failure is visible without reading logs.

Engineering validation:

- `backend/tests/unit/test_admin_eval_golden_set.py`
- `backend/tests/unit/test_jobs.py`

### Iteration 4: Frontend Job Visibility

Status: planned.

Purpose: make jobs visible without turning the admin UI into a monitoring
product.

Work:

- Add API client types.
- Add recent jobs panel or drawer.
- Show job status/progress/error.
- Link document jobs to document detail when possible.
- Link eval jobs to latest eval result when possible.

Exit criteria:

- Admin can diagnose active/recent jobs from the UI.
- No existing document/eval workflow becomes harder to use.

### Iteration 5: Manual Validation And P2 Decision

Status: planned.

Purpose: test reliability and decide whether retry/cancel/reparse should move
from P2 to active scope.

Manual checks:

- process a normal Markdown document
- process a Markdown zip with images
- trigger a failed document job
- retry a failed document job
- run retrieval-only eval
- run answer-lite or full eval
- restart backend while a job is running if practical

Closeout:

- Record failures or noisy job states.
- Decide whether P2.1 retry and P2.3 reparse/reindex should start immediately.
- Mark Phase 14 P1 complete only after manual checks pass.

## Acceptance Criteria

P1 is complete when:

- New job records exist for document processing/retry and eval runs.
- Admin can list and inspect recent jobs.
- Stale running jobs are marked failed/recoverable on startup.
- Document status and job status remain consistent.
- Failed document/eval jobs include useful error details.
- Existing endpoints still work for current frontend callers.

P2 is complete when:

- Supported failed jobs can be retried explicitly.
- Safe cancellation is available where truthful.
- Completed documents can be reparse/reindexed through a job-backed workflow.
- Slow or partial cleanup flows are job-backed if needed.
