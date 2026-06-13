# Refactoring Plan

Historical snapshot, refreshed on 2026-06-03 after Phase 11-14 and Storage Phase 1. This document tracks structural refactoring work only: reducing duplicate orchestration, splitting oversized files, and keeping behavior-preserving changes testable. It is not a live size dashboard; refresh the counts before using them to plan a new refactor.

## Current State

| | Backend | Frontend |
|---|---:|---:|
| Lines of code | 13,050 | 15,176 |
| Source files | 90 | 51 |
| Test files | 50 | build only |
| Largest file | `admin_eval.py` 710 | `EvalRunPanel.vue` 1,765 |

Module distribution (backend):

```text
app/api/          16 files
app/core/          5 files
app/models/        2 files
app/rag/          47 files
  rag/chunking/    5 files
  rag/embeddings/  2 files
  rag/ingestion/   5 files
  rag/parsing/     4 files
  rag/query/      27 files
  rag/vectorstores/3 files
app/services/     11 files
app/utils/         4 files
```

Large files after Phase 14 / Storage Phase 1:

| File | Lines | Note |
|---|---:|---|
| `frontend/src/components/evaluate/EvalRunPanel.vue` | 1,765 | Candidate for a later frontend-only split |
| `frontend/src/components/retrieval-test/RetrievalTestView.vue` | 1,327 | Candidate for a later UI split; not part of Phase C because service-side retrieval test seams were already split |
| `frontend/src/components/evaluate/QueryStatsRecords.vue` | 1,227 | Candidate for query stats table/filter split |
| `frontend/src/components/documents/DocumentDetailView.vue` | 943 | Candidate if document detail behavior grows |
| `frontend/src/components/evaluate/EvalCaseDetailDrawer.vue` | 839 | Candidate if eval result details keep growing |
| `backend/app/api/admin_eval.py` | 710 | Candidate for service extraction if eval admin flow grows |
| `frontend/src/components/documents/DocumentsView.vue` | 655 | Candidate if upload/list behavior grows |
| `frontend/src/components/settings/SettingsView.vue` | 652 | Now an orchestration parent for settings panels |
| `backend/app/rag/chunking/markdown_chunker.py` | 549 | Large but cohesive parser/chunker logic |
| `frontend/src/components/settings/TagGovernancePanel.vue` | 547 | Cohesive but near the split threshold; monitor after future tag features |
| `frontend/src/components/query-chat/RetrievalInfo.vue` | 542 | Candidate if retrieval explanation UI grows |
| `backend/app/services/document_service.py` | 539 | Candidate if document orchestration grows again |
| `backend/app/services/query_stats_service.py` | 527 | Candidate if stats query/detail logic grows |
| `backend/app/api/query_chat.py` | 516 | Phase B removed retrieval orchestration; remaining complexity is SSE/stats/observability |

---

## Completed Phases

### Phase A: Deduplicate Helper Functions

Status: completed.

Completed work:

- Centralized admin auth check in `app/core/auth.py`.
- Centralized timing helper in `app/utils/time.py`.
- Centralized Milvus hit parsing in `app/rag/vectorstores/milvus_hits.py`.
- Extracted frontend `ChunkTagList.vue` for shared structured-tag rendering.
- Addressed Phase A review findings: output fields, remaining `tick_ms` call sites, JSON list reuse, and dead retrieval-test helpers.

### Phase B: Unify Search Pipeline Entry Point

Status: completed.

Completed work:

- Added `app/rag/query/search_pipeline.py` as the shared retrieval runner.
- `api/query_chat.py` now delegates retrieval to the shared runner and keeps SSE, generation, validation, groundedness, and stats persistence.
- `rag/query/graph.py` is now a thin non-streaming entry point that delegates retrieval to the shared runner, then builds prompt/generates/validates.
- `services/retrieval_test_service.py` delegates retrieval to the shared runner with hooks for retrieval-path labeling and with post-rerank fallback disabled to preserve previous retrieval-test behavior.
- Removed the unused query-side `StateGraph` declaration.
- Added focused runner and non-streaming graph tests.

Result:

- Retrieval pipeline assembly is no longer duplicated across `graph.py`, `query_chat.py`, and `retrieval_test_service.py`.
- The remaining duplication in `retrieval_test_service.py` is mostly adapter/test seam code, not a second pipeline definition.

---

## Phase B.1: Plan Refresh

Risk: low. Documentation only.

Status: this document.

Purpose:

- Mark Phase A and Phase B complete.
- Refresh current file paths and line counts.
- Re-rank the next work now that retrieval orchestration has moved to `search_pipeline.py`.
- Downgrade the old Phase D from a planned merge to a small audit, because `structured_tags.py` already uses `get_structured_tag_definition()` for effective API records.

---

## Phase C: Split Large Files

Risk: low to medium. Keep changes behavior-preserving and split one responsibility per commit.

Status: completed for the planned structural split targets.

Completed work:

- C4 split `backend/app/services/document_service.py` into orchestration plus:
  - `backend/app/services/document_chunk_query.py`
  - `backend/app/services/document_cleanup.py`
- C2 split `backend/app/services/retrieval_test_service.py` into orchestration plus:
  - `backend/app/services/retrieval_test_search.py`
  - `backend/app/services/retrieval_test_formatting.py`
- C1 split `frontend/src/components/settings/SettingsView.vue` into an orchestration parent plus:
  - `SystemStatusPanel.vue`
  - `StrategyTuningPanel.vue`
  - `TokenSettingsPanel.vue`
  - `TagGovernancePanel.vue`
- C3 was intentionally left alone: `query_chat.py` is 380 lines after Phase B and its remaining SSE/generation/stats flow is still cohesive.

Result:

- `document_service.py` is now focused on document CRUD, processing, and high-level delete/repair orchestration.
- `retrieval_test_service.py` keeps stable public test seams while moving retrieval variants and result shaping into helper modules.
- `SettingsView.vue` dropped from 1,524 lines to 622 and now delegates each tab body to a focused panel component.

Verification:

- Backend unit tests after backend service splits.
- `npm run build`
- Manual smoke check of Settings page tabs/forms after build.

---

## Phase D: Structured Tag Override Audit

Risk: low.

Status: completed.

Previous concern:

- Earlier plans assumed API response merging and runtime override merging were independently implemented.

Current state:

- `api/structured_tags.py` builds effective admin records through `apply_structured_tag_override()` using override rows it just read.
- `structured_tag_registry.py` remains the runtime source of truth for normalized/search-time tag behavior.
- API-side direct DB reads are still needed for override metadata such as `overridden` and `updated_at`.

Plan:

1. Audited `_tag_record()` and registry override tests after Phase C.
2. Added `apply_structured_tag_override()` in `structured_tag_registry.py` so runtime registry behavior and admin API record construction share the same effective-value merge logic.
3. Kept API-side override reads because admin records still need metadata such as `overridden` and `updated_at`.
4. Added regression coverage for stale registry cache vs freshly read API override rows.

Result:

- Registry remains the runtime source for normalized/search-time structured tag definitions.
- Admin API records now apply the override row they just read, avoiding an extra registry cache lookup while preserving the same effective-value semantics.
- Override metadata remains API-owned until the registry exposes a richer metadata object.

---

## Phase E: Test Coverage

Not a standalone implementation phase. Add tests during each refactoring step.

Status: coverage pass 3 completed.

Completed work:

- Added direct tests for `document_chunk_query.py`:
  - Milvus query failure falls back to parsed chunks.
  - Single chunk lookup falls back to parsed chunks after Milvus failure.
  - parsed artifact loading filters invalid rows.
  - chunk normalization parses JSON/list metadata and derives stable chunk keys.
- Added direct tests for `document_cleanup.py`:
  - Milvus delete failure returns `partial`, records cleanup status/error event, keeps the DB record, and still clears local artifacts/cache.
- Added direct tests for `direct_search.py`:
  - balanced retrieval runs primary search + HyDE and fuses shared hits through RRF.
  - exact retrieval disables HyDE even if the raw config toggle is enabled.
  - recall/query-expansion retrieval searches variants and isolates one failed expanded query.
- Added direct tests for `filter_utils.py`:
  - Milvus string escaping for quotes and backslashes.
  - ACL/entity filter expression construction.
  - filter combination semantics.
  - distinction between missing ACL (`None`) and empty ACL (`[]`).

Priority order:

1. Completed: `document_service.py` extraction tests or focused regression tests for chunk query/delete behavior.
2. Completed: `direct_search.py` orchestration tests, especially search + HyDE + RRF.
3. `search_pipeline.py` branch tests as new retrieval behavior is added.
4. Completed: `filter_utils.py` ACL/entity filter tests because this is security-relevant.
5. Frontend build coverage for component splits.

---

## Recommended Execution Order

```text
B.1 (refresh this plan)
   ↓
C4  (split document_service.py)
   ↓
C2  (consider retrieval_test_service.py split only if still useful)
   ↓
C1  (split SettingsView.vue)
   ↓
D   (structured tag override audit)
   ↓
Next frontend/backend split only when a file grows around a real workflow change
```

Reasoning:

- Phase A and Phase B are complete and should not be mixed with the next structural phase.
- `document_service.py` is the best next target: clear boundaries, backend tests, moderate file size.
- `retrieval_test_service.py` still has useful test seams, so defer aggressive cleanup.
- `SettingsView.vue` is the largest file, but frontend splits are harder to verify automatically and should happen after the backend service split.
- Phase D stayed a small audit because the originally planned merge had mostly already happened.

---

## Out of Scope

- Performance optimization without measured bottlenecks.
- New product features.
- Database schema changes.
- API contract changes.
- Frontend build or bundling changes.
- Adding a monorepo tool or workspace structure.
