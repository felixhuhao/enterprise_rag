# Phase 12: Query Observability And Latency/Cost Profile

Last updated: 2026-06-02

## Goal

Make every query explainable by stage timing, retrieval path, resolved settings, result shape, token usage, fallback behavior, and failure reason.

Phase 12 is successful when a slow or low-quality query can answer these questions without reading backend logs:

- Which stage was slow?
- Which retrieval settings were actually used?
- Did entity routing, fallback, HyDE, query expansion, rerank, or context expansion change the result?
- How many chunks entered each major stage?
- Did generation and citation behavior match the retrieved context?
- Which model and token usage drove cost?

## Current Baseline

The project already has useful observability pieces:

- `query_run_stats` persists online query records.
- Query stats already track total latency, retrieval latency, generation latency, rerank scores, result count, flavor, strict evidence, fallback, groundedness, and citations.
- Streaming chat already emits trace events and rerank debug data.
- Retrieval test already exposes retrieval trace data.
- Phase 11 evaluation stores per-case traces and failure categories.

The gap is not lack of signals. The gap is consistency:

- Stage traces are not persisted as a first-class structured field.
- Resolved query settings are scattered across state, config, trace, and UI display.
- Result-shape metrics are partial.
- Token usage and model usage are not consistently recorded.
- Non-streaming query paths are less observable than streaming paths.
- The stats UI can show records, but cannot yet explain one query deeply.

## Scope Boundary

Phase 12 is an observability and operations phase. It should not change retrieval ranking logic unless a small instrumentation helper requires it.

In scope:

- Normalize query observability data.
- Persist structured trace/settings/result-shape/token fields.
- Add per-query detail APIs.
- Add stage-level latency summaries.
- Improve query stats UI so slow/error/fallback cases are inspectable.
- Cover streaming and non-streaming query paths.

Out of scope:

- New retrieval algorithms.
- Evaluation scoring changes.
- Full A/B testing system.
- External APM/OpenTelemetry integration.
- Cost billing or quota enforcement.
- Large analytics dashboard.
- Data warehouse integration.

## P1 Scope

P1 is the minimum useful observability loop: every production query should leave behind enough structured data to explain performance and behavior.

### P1.1 Observability Payload Shape

Define one normalized payload shape that can be built from query state and saved in `query_run_stats`.

Suggested shape:

```json
{
  "query_id": "qr_...",
  "endpoint": "query_chat_stream",
  "status": "success",
  "error_code": "",
  "retrieval_flavor": "balanced",
  "strict_evidence": false,
  "timings_ms": {
    "rewrite": 120,
    "hyde": 300,
    "query_expansion": 40,
    "search": 310,
    "rrf_fusion": 8,
    "table_expand": 15,
    "rerank": 480,
    "diversify_context": 4,
    "context_expand": 45,
    "prompt_build": 12,
    "generate": 2100,
    "total": 3100
  },
  "resolved_settings": {
    "retrieval_flavor": "balanced",
    "strict_evidence": false,
    "entity_mode": "single",
    "selected_entities": ["星辰科技"],
    "search_limit": 24,
    "rerank_candidate_k": 10,
    "final_context_k": 5,
    "use_hybrid": true,
    "use_hyde": true,
    "use_rerank": true
  },
  "result_shape": {
    "retrieved_chunks_count": 24,
    "rerank_candidates_count": 10,
    "final_context_chunks_count": 5,
    "citations_count": 4,
    "avg_rerank_score": 0.71,
    "top_rerank_score": 0.88,
    "empty_result_reason": ""
  },
  "fallback_info": {
    "used": false,
    "blocked": false,
    "reason": ""
  },
  "token_usage": {
    "model": "qwen-plus",
    "prompt_tokens": 3200,
    "completion_tokens": 420,
    "total_tokens": 3620
  }
}
```

Implementation preference:

- Add a small backend helper that builds this payload from `QueryState`, trace dicts, config, citation result, groundedness result, and generation metadata.
- Keep raw trace compatibility for current UI components.
- Do not let UI code infer missing operational facts from display labels.

### P1.2 Persist Structured Observability Fields

Reuse `query_run_stats`; do not create a separate analytics system.

Add compact JSON columns or equivalent fields for:

- `timings_json`
- `settings_json`
- `result_shape_json`
- `fallback_json`
- `token_usage_json`
- `endpoint`

Keep existing scalar columns for list filtering and backward compatibility:

- `retrieval_wall_ms`
- `first_token_ms`
- `generate_ms`
- `total_ms`
- `result_count`
- `rerank_avg_score`
- `rerank_top_score`
- `retrieval_flavor`
- `strict_evidence`
- `fallback_used`
- `status`
- `error_code`

### P1.3 Stage Timing Coverage

Record stage-level timing where the stage exists:

- entity confirmation
- query planning
- query rewrite
- HyDE
- query expansion
- dense/sparse search
- RRF fusion
- table expansion
- rerank
- post-rerank fallback
- context diversification
- context expansion
- multi-hop discovery
- prompt build
- citation validation
- groundedness when enabled
- answer generation
- total wall time

Missing or disabled stages should be absent or zero consistently. The UI should distinguish "not run" from "ran in 0 ms" when practical.

### P1.4 Resolved Query Settings

Persist the settings that actually affected the query, not only user inputs.

Required fields:

- retrieval flavor
- strict evidence
- entity mode
- selected entities
- fallback policy and fallback result
- retrieval budget
- search limit
- rerank candidate count
- final context count
- hybrid on/off
- HyDE on/off
- rerank on/off
- model names used for generation/rerank/groundedness when available

This is especially important because dynamic retrieval budget and query flavor logic can change the effective behavior.

### P1.5 Result-Shape Metrics

Persist enough counts to explain whether a query failed because nothing was retrieved, rerank discarded evidence, context was too small, or citation extraction failed.

Required fields:

- retrieved chunk count (`retrieved_chunks_count`)
- rerank candidate count (`rerank_candidates_count`)
- final context chunk count (`final_context_chunks_count`)
- citation count (`citations_count`)
- retrieved document count (`retrieved_documents_count`)
- cited document count (`cited_documents_count`)
- average rerank score
- top rerank score
- empty result reason
- fallback used/blocked/reason

### P1.6 Token Usage Basics

Record basic token usage when the model provider returns it.

Required fields:

- model name
- prompt tokens
- completion tokens
- total tokens

P1 does not need accurate cost estimation. Missing token usage should be explicit rather than silently treated as zero.

### P1.7 Query Stats API

Add or extend APIs so the frontend can inspect one query deeply.

Required API behavior:

- List records still returns compact fields.
- Detail endpoint returns one query run with structured observability payload.
- Aggregates expose p50/p95 latency by:
  - retrieval flavor
  - status
  - endpoint
- Stage-level p50/p95 is available for the main timing fields.

### P1.8 Frontend Query Stats Detail

Improve the existing query stats UI; do not build a separate analytics product.

Minimum UI:

- Query record list remains scannable.
- Each row can open a detail view.
- Detail view shows:
  - stage timing breakdown
  - resolved settings
  - result shape
  - fallback info
  - token usage
  - citations/retrieved chunks when already available
- Slow queries should visually surface the slowest stage.

### P1.9 Streaming And Non-Streaming Coverage

Both query paths must save comparable stats:

- streaming `/query/chat/stream`
- non-streaming `/query/chat`

Error paths should also be saved:

- empty result
- timeout
- client abort
- LLM error
- embedding/search/rerank error
- citation/groundedness failure when applicable

## P2 Scope

P2 turns observability from "debuggable" into "operationally useful."

### P2.1 Cost Estimation

Add cost estimation only after token usage is stable.

Potential fields:

- provider
- model
- input token price
- output token price
- estimated cost
- currency

Potential summaries:

- cost by day
- cost by user
- cost by retrieval flavor
- cost by endpoint
- cost by model

### P2.2 Multi-Call Token Attribution

Split token usage by LLM call type:

- query rewrite
- HyDE
- rerank
- answer generation
- groundedness
- judge/evaluation if applicable

This is useful, but P1 should not block on it because providers expose usage inconsistently.

### P2.3 Advanced UI

Add richer visual analysis only after the data model is stable.

Candidates:

- stage latency heatmap
- slow query drilldown
- fallback distribution chart
- error-code distribution
- model/token/cost trend
- query run comparison
- export JSON/CSV

### P2.4 Retention And Sampling

Add operational controls if data volume becomes a problem:

- trace retention days
- raw trace cleanup
- sampling percentage
- maximum retrieved chunks stored per run
- maximum citation payload stored per run

### P2.5 External Observability

Do not introduce this until local stats are useful.

Candidates:

- OpenTelemetry spans
- Prometheus metrics
- Grafana dashboard
- APM integration

## Implementation Iterations

The P1 scope above is the logical feature breakdown. Implementation should be grouped by data flow to avoid repeated schema/API churn.

### Iteration 1: Data Model And Payload Helper

Status: implemented on 2026-06-02.

Purpose: create the stable observability shape before changing query paths.

Work:

- Define the normalized observability payload helper.
- Add `query_run_stats` columns:
  - `timings_json`
  - `settings_json`
  - `result_shape_json`
  - `fallback_json`
  - `token_usage_json`
  - `endpoint`
- Keep existing scalar stats columns for compatibility.
- Add unit tests for payload normalization and JSON serialization.

Maps to:

- P1.1 Observability Payload Shape
- P1.2 Persist Structured Observability Fields

Exit criteria:

- A payload can be built from representative query state without hitting the API.
- Existing query stats reads still work against old and migrated rows.

### Iteration 2: Streaming Query Write Path

Status: implemented on 2026-06-02.

Purpose: make the main chat stream save full observability data.

Work:

- Save structured payload from `/query/chat/stream`.
- Fill stage timings from the existing trace dict.
- Fill resolved settings from query plan/config/state.
- Fill result shape from search results, rerank debug, citations, and fallback info.
- Record basic token usage if provider metadata is available; otherwise store explicit empty fields.

Maps to:

- P1.3 Stage Timing Coverage
- P1.4 Resolved Query Settings
- P1.5 Result-Shape Metrics
- P1.6 Token Usage Basics

Exit criteria:

- A normal streaming chat query creates a stats row with timings/settings/result shape/fallback/token fields.
- Existing chat UI trace behavior is unchanged.

### Iteration 3: Non-Streaming And Error Paths

Status: implemented on 2026-06-02.

Purpose: remove observability blind spots.

Work:

- Make non-streaming `/query/chat` save comparable observability data.
- Persist structured error rows for:
  - empty result
  - timeout
  - client abort where observable
  - LLM error
  - embedding/search/rerank error
  - citation/groundedness failure when applicable
- Ensure `status`, `error_code`, `endpoint`, and timing fields are populated consistently.

Maps to:

- P1.9 Streaming And Non-Streaming Coverage

Exit criteria:

- Streaming and non-streaming stats rows can be compared by the same API fields.
- Expected error paths are classified and visible in query records.

### Iteration 4: Query Stats API

Status: implemented on 2026-06-02.

Purpose: expose the persisted observability data without forcing the UI to infer internals.

Work:

- Extend records API with compact observability fields.
- Add query run detail endpoint.
- Add p50/p95 aggregations grouped by:
  - retrieval flavor
  - status
  - endpoint
- Add stage-level p50/p95 summaries for major timing keys.

Maps to:

- P1.7 Query Stats API

Exit criteria:

- One query record can be fetched with the full structured payload.
- Admin can compare latency by flavor/status/endpoint through API responses.

### Iteration 5: Frontend Query Detail

Status: implemented on 2026-06-02.

Purpose: make the data useful from the admin UI.

Work:

- Keep the query records list compact.
- Add an inspectable detail drawer or expandable row.
- Show:
  - stage timing breakdown
  - slowest stage highlight
  - resolved settings
  - result shape
  - fallback info
  - token usage
  - retrieved chunks and citations when already available
- Avoid a large dashboard in P1.

Maps to:

- P1.8 Frontend Query Stats Detail

Exit criteria:

- Admin can diagnose one slow/fallback/error query from the UI without reading logs.

### Iteration 6: Validation And Phase Closeout

Status: engineering validation completed on 2026-06-02. Live query/UI manual
checks should be run after rebuilding the backend image, because the currently
running backend container may still contain an older image.

Purpose: verify the loop on real query patterns before moving to P2.

Manual checks:

- Normal successful query.
- Strict evidence query.
- Fallback used.
- Fallback blocked.
- Empty-result query.
- Generation error or timeout if it can be simulated safely.
- Non-streaming query.

Closeout:

- Confirm stats rows contain comparable payloads.
- Confirm API summaries are stable with mixed old/new rows.
- Confirm UI detail explains the query without backend logs.
- Update this document with completed status and any deferred P2 findings.

Engineering validation completed:

- `python -m compileall backend/app/services/query_observability.py backend/app/services/query_stats_service.py backend/app/api/query_chat.py backend/app/api/query_stats.py`
- `npm --prefix frontend run build`
- `git diff --check`
- Query stats service smoke with an in-memory SQLite database:
  - old scalar-only row stays readable
  - new structured observability row decodes timings/settings/result shape/fallback/token fields
  - detail lookup applies user filtering
  - latency breakdown groups by flavor/status/endpoint and stage timings

Validation limits:

- `pytest` is not installed in the local Python environment or the current backend container, so `test_query_stats.py` was not run through pytest.
- The current backend container did not include `query_observability.py`, indicating it needs a rebuild before live API/UI validation.

Deferred P2 findings:

- Add a time range such as `days` or `since` to the latency breakdown API before query stats volume grows large.
- Consider flattening nested `budget` and `fallback_policy` values in the query detail UI for easier scanning.
- Replace the remaining raw JSON display for deeply nested settings with grouped rows once the data shape stabilizes.

## Acceptance Criteria

P1 is complete when:

- A slow query can be attributed to one or more specific stages.
- A fallback query clearly shows why fallback was used or blocked.
- A retrieval regression can be inspected with result counts before and after rerank/context selection.
- Admin can inspect one query run from the UI without reading logs.
- Admin can compare p50/p95 latency by retrieval flavor and status.
- Token usage and model names are visible when provider metadata exists.
- Streaming and non-streaming query paths save comparable records.
- Error cases are classified and persisted.

P2 is complete when:

- Token usage can be translated into estimated cost.
- Cost can be grouped by user, model, endpoint, and retrieval flavor.
- Stage-level latency trends can be reviewed without opening individual query rows.
- Observability data has retention or cleanup controls if needed.

## Not Doing In Phase 12

- No new retrieval strategy.
- No golden set rewrite.
- No automated root-cause classifier beyond explicit error/fallback/result-shape fields.
- No billing or quota system.
- No OpenTelemetry/APM unless P1 data shape is already proven useful.
- No large dashboard before the per-query detail view works.
