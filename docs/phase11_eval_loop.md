# Phase 11: Golden Set Evaluation Loop And Fast Eval Modes

Last updated: 2026-06-03

Status: complete. Fast eval modes, retrieval-only scoring, answer-lite scoring,
judge cache, concurrency, accepted-baseline deltas, failure categories, and UI
case details are implemented and manually validated.

Current product semantics:

- `retrieval_only`, `answer_lite`, and `full` are the three main run modes.
- The smoke set is a case subset filter, not a separate product mode.
- The backend still accepts `quick` as a compatibility path for quick-tagged
  cases, but the UI presents this as 冒烟集 selection.

## Goal

Turn the current golden set from a slow full-pipeline smoke test into a practical evaluation loop that developers can run frequently.

The phase is successful when evaluation can answer three questions quickly:

- Did retrieval find the expected evidence?
- Did answer generation use the evidence correctly?
- Did the change improve quality without hiding latency or timeout regressions?

## Scope Boundary

Phase 11 is an evaluation and reporting phase. It should not add new retrieval algorithms.

In scope:

- Fast evaluation modes.
- Retrieval-only evaluation.
- Quick representative subset.
- Golden case schema additions needed by those modes.
- Per-case retrieval and answer metrics.
- Run summaries.
- Admin/API/script support for choosing evaluation mode.

Out of scope:

- New retrieval algorithms.
- Section probe retrieval.
- Doc2Query.
- Automatic golden set rewriting.
- Full annotation platform.
- Parameter sweep / A-B testing system.
- Scheduled/nightly job system.
- Large case-management UI.

## Evaluation Modes

### `retrieval_only`

Purpose: run all cases quickly and isolate recall/rerank/context failures before generation.

Behavior:

- Run query planning and retrieval pipeline.
- Return top retrieved/reranked chunks and trace fields.
- Do not generate final answer.
- Do not run LLM judge.
- Score expected document/chunk hits.

Primary metrics:

- `Hit@5`
- `Hit@10`
- expected document coverage
- expected chunk coverage
- retrieval latency
- timeout count

### `quick`

Purpose: small pre-commit/full-flow smoke test.

Behavior:

- Run 5-8 representative cases.
- Run the normal answer path.
- Prefer rule/citation/expected-point checks.
- LLM judge is off by default unless explicitly requested.

Required coverage:

- One exact lookup case.
- One recall-heavy case.
- One multi-entity case.
- One no-answer case.
- One table/amount-threshold case.
- One permission-sensitive case if ACL is enabled in the test environment.

### `answer_lite`

Purpose: answer-generation check without paying full judge cost.

Behavior:

- Run selected or all cases through generation.
- Judge is disabled, cached, or explicitly opt-in.
- Use expected points, citations, no-answer rules, and groundedness when available.

This mode is P2. P1 may define the enum and route but does not need a polished implementation.

### `full`

Purpose: release/regression run.

Behavior:

- Run all enabled cases.
- Run answer generation.
- Run LLM judge when configured.
- Produce full retrieval, answer, citation, and latency summary.

This mode already exists in partial form; Phase 11 should make it coexist cleanly with faster modes.

## P1 Scope

P1 is the minimum useful loop: fast enough to run often and clear enough to separate retrieval failures from answer failures.

### P1.1 Evaluation Mode Plumbing

Add `mode` support to:

- CLI/script runner.
- Admin eval API.
- Frontend eval run panel.
- Eval output metadata.

Required modes:

```text
retrieval_only
quick
full
```

`answer_lite` may exist as an accepted value only if it is cheap to wire, but it does not need full P1 behavior.

### P1.2 Retrieval-Only Runner

Add a backend path that runs retrieval without answer generation.

Preferred implementation:

- Call the shared query/search pipeline directly.
- Avoid opening a chat SSE stream and aborting it.
- Return normalized hits, trace, timings, retrieval flavor, and retrieval path.

Required output per case:

- top chunks
- top documents
- expected doc/chunk match flags
- `Hit@5`
- `Hit@10`
- retrieval latency
- retrieval flavor
- entity mode
- fallback info when available

### P1.3 Quick Subset

Add deterministic quick case selection.

Preferred schema:

```json
{
  "id": "exact_policy_001",
  "quick": true,
  "slices": ["exact", "policy_lookup"]
}
```

Rules:

- Quick cases must be explicit and stable.
- Do not randomly sample quick cases.
- Keep the quick subset small enough to run before a commit.
- Include hard cases, not only happy paths.

### P1.4 Golden Case Schema Additions

Add only the fields needed for fast modes and retrieval scoring.

Recommended fields:

```json
{
  "id": "recall_agg_001",
  "question": "...",
  "quick": true,
  "slices": ["recall", "amount_threshold"],
  "expected_docs": ["12_年度培训计划_2026"],
  "expected_chunk_keys": ["..."],
  "expected_points": ["..."],
  "expected_behavior": "answer"
}
```

Field notes:

- `expected_docs`: document-level recall target.
- `expected_chunk_keys`: stronger chunk-level recall target when stable.
- `expected_points`: answer-level target.
- `expected_behavior`: `answer` or `no_answer`.
- `slices`: used for grouped reporting.
- `quick`: marks stable quick subset.

### P1.5 Summary Output

Every run should store a compact summary.

Required summary fields:

```json
{
  "mode": "retrieval_only",
  "flavor": "balanced",
  "case_count": 30,
  "passed": 24,
  "failed": 6,
  "hit_at_5": 0.82,
  "hit_at_10": 0.9,
  "citation_hit_rate": null,
  "answer_pass_rate": null,
  "latency_p50_ms": 850,
  "latency_p95_ms": 1800,
  "timeout_count": 0,
  "output_path": "data/eval_runs/..."
}
```

Answer-only fields may be `null` in `retrieval_only`.

### P1.6 UI/API Minimum

Minimum frontend/API behavior:

- Admin can choose `retrieval_only`, `quick`, or `full`.
- Latest run summary shows mode, case count, pass/fail, key metrics, timeout count, and output path.
- Failed cases are identifiable from the output file even if the UI does not yet have a rich detail table.

## P2 Scope

P2 makes the loop comfortable and scalable as the golden set grows.

### P2.1 Judge Cache

Cache judge results by:

```text
case_id
normalized_answer
expected_answer / expected_points
judge_model
rubric_version
```

Rules:

- Do not cache retrieval metrics.
- Reuse cached judge only when the generated answer and judge inputs are unchanged.
- Show whether a judge result was fresh or cached.

### P2.2 Limited Concurrency

Add bounded concurrency:

- Retrieval-only can run with higher concurrency.
- Generation and judge should use lower concurrency.
- Timeouts should fail one case, not the whole run.

The concurrency cap should be configurable and conservative by default.

### P2.3 Baseline Comparison

Store an accepted baseline summary and compare current runs against it.

Show deltas for:

- `Hit@10`
- citation hit rate
- answer pass rate
- p95 latency
- timeout count

Baseline comparison should be grouped by mode and retrieval flavor.

### P2.4 Failure Classification

Add structured failure categories.

Current implementation already supports coarse categories:

```text
retrieval_miss
citation_miss
answer_incomplete
no_answer_wrong
timeout
unknown
```

The remaining P2.4 work is to add best-effort fine-grained categories where the
available result row contains enough evidence:

```text
rerank_drop
context_loss
answer_unsupported
judge_uncertain
```

Rules:

- Keep internal category keys stable and separate from UI labels.
- A case may have multiple categories.
- Do not invent unsupported precision. If the trace/result row cannot distinguish
  `rerank_drop` from `context_loss`, keep the coarse category.
- Manual correction belongs to a later annotation workflow.

### P2.5 Report UI

Improve the admin eval page with a minimum reusable diagnostic surface.

Minimum useful scope:

- Add a failed/warning cases table for the latest run.
- Support simple filtering by:
  - failure category
  - retrieval flavor
- Add a reusable case detail drawer that shows:
  - question
  - expected points
  - expected docs
  - expected chunk keys
  - actual answer
  - actual citations
  - top rerank/retrieval results
  - `Hit@5` / `Hit@10`
  - doc/chunk hit flags
  - failure categories
  - judge result / reason / cache status
  - trace latency
  - timeout/error
- Add a backend result detail endpoint instead of putting full result rows into
  the status polling payload.
- Keep the first UI version connected only to the latest run.

Reusable module boundary:

- Backend detail endpoint should read a result row from an eval results JSONL file.
- Frontend should split reusable components from `EvalRunPanel.vue`:
  - `EvalCaseTable.vue`
  - `EvalCaseDetailDrawer.vue`
- The drawer should consume the existing eval result row schema, not a second
  bespoke schema.

Not doing in the minimum version:

- No historical run list.
- No previous-run comparison UI.
- No charts.
- No manual failure-category correction.
- No full chunk-content highlighting.
- No export workflow.

Acceptance:

- After a run, the UI lists all failed/warning cases without opening JSONL.
- Opening a case shows enough evidence to decide whether the failure is retrieval,
  citation, answer, judge, or timeout related.
- The table/drawer can be reused later for history and baseline views.

### P2.6 Answer-Lite Mode

Make `answer_lite` useful:

- Generate answers.
- Skip judge by default.
- Use expected points, citation hit, no-answer rules, and groundedness when available.
- Use judge cache if available.
- Optionally allow explicit judge-on override.

## Metrics

Retrieval metrics:

- `Hit@5`
- `Hit@10`
- expected document coverage
- expected chunk coverage
- average retrieval latency
- p50 retrieval latency
- p95 retrieval latency
- timeout count

Answer metrics:

- answer pass rate
- expected point coverage
- citation hit rate
- no-answer correctness
- groundedness / faithfulness score when available
- judge score when enabled

Run metadata:

- mode
- retrieval flavor
- case count
- enabled case count
- skipped case count
- model names
- output path
- started_at / finished_at

## Acceptance Criteria

P1 acceptance:

- `retrieval_only` can run all current golden cases without answer generation or judge.
- `quick` runs a stable representative subset.
- Admin/API/script can choose eval mode.
- Summary output includes retrieval metrics and latency.
- Failed retrieval cases can be identified from output.

P2 acceptance:

- Judge cache prevents repeated judge cost for unchanged answers.
- Concurrency shortens wall-clock time without hiding per-case failures.
- Baseline comparison shows quality and latency deltas.
- Failure categories are visible in reports.
- `answer_lite` provides a useful middle path between retrieval-only and full judge.

## Open Decisions For Iteration Planning

These should be resolved when splitting the phase into implementation iterations:

- Whether retrieval-only should call `run_search_pipeline` directly or use a thin query-graph wrapper.
- Which existing JSONL fields are stable enough for `expected_chunk_keys`.
- How many quick cases to mark initially.
- Whether `quick` should default to `balanced` only or run each case with its configured flavor.
- Where run summaries should live: SQLite, JSON sidecar, or both.
- How much detail the first UI pass needs versus relying on output files.

## Iteration Plan

Each iteration should leave the project in a usable state. Do not start P2 work until P1 is useful from script/API/UI.

### Iteration 1: Mode Plumbing And Case Selection

Goal: make evaluation mode a first-class input without changing retrieval behavior yet.

Scope:

- Add `mode` to the eval script/API request/output metadata.
- Support accepted modes:
  - `retrieval_only`
  - `quick`
  - `full`
- Preserve existing full-run behavior as `full`.
- Add quick case selection.
- Add minimal schema support for:
  - `quick`
  - `slices`
  - `expected_docs`
  - `expected_chunk_keys`
  - `expected_behavior`
- Mark the first 5-8 quick cases.
- Ensure invalid mode values fail clearly.

Not doing:

- No retrieval-only implementation yet if it would complicate the first diff.
- No UI report redesign.
- No judge cache.
- No concurrency.

Acceptance:

- Existing full eval still works.
- Eval output records `mode`.
- `quick` runs only the marked subset.
- Case loading tolerates old cases without new optional fields.

Suggested verification:

```bash
python backend/scripts/eval_golden_set.py --mode full --limit 1
python backend/scripts/eval_golden_set.py --mode quick
```

### Iteration 2: Retrieval-Only Runner

Goal: run all golden cases through retrieval without answer generation or judge.

Scope:

- Implement `retrieval_only` mode.
- Call the shared query/search pipeline directly, or add a thin backend helper around it.
- Return normalized retrieval results per case:
  - top chunks
  - top documents
  - retrieval flavor
  - entity mode
  - fallback info
  - retrieval trace
  - retrieval latency
- Compute retrieval metrics:
  - `Hit@5`
  - `Hit@10`
  - expected document hit
  - expected chunk hit when `expected_chunk_keys` exists
- Ensure retrieval-only never calls answer generation or LLM judge.

Not doing:

- No baseline comparison.
- No UI detail table.
- No generated-answer scoring.

Acceptance:

- `retrieval_only` can run the current 30 cases.
- Output clearly identifies retrieval misses.
- Runtime is materially faster than full generation/judge eval.
- A case with no `expected_chunk_keys` can still score document-level hits.

Suggested verification:

```bash
python backend/scripts/eval_golden_set.py --mode retrieval_only
```

### Iteration 3: Summary Output And Admin UI Minimum

Goal: make the new modes usable from the product UI and produce compact run summaries.

Scope:

- Store compact run summary with:
  - mode
  - flavor
  - case count
  - passed / failed
  - `Hit@5`
  - `Hit@10`
  - citation hit rate when applicable
  - answer pass rate when applicable
  - p50 / p95 latency
  - timeout count
  - output path
- Add eval mode selector to admin eval UI.
- Show latest summary in the UI.
- Ensure `retrieval_only` summaries show answer-only fields as null or not applicable.
- Ensure failed case ids are visible through the output file or existing report view.

Not doing:

- No rich case detail drawer.
- No historical comparison.
- No charts unless existing UI makes them cheap.

Acceptance:

- Admin can run `quick`, `retrieval_only`, and `full` from UI.
- Latest run clearly shows mode and key metrics.
- Output files remain inspectable and linked.

Suggested verification:

```bash
npm --prefix frontend run build
pytest backend/tests/unit -q
```

### Iteration 4: Failure Categories And Answer-Lite Skeleton

Goal: separate failure types enough to guide debugging, and reserve the middle mode cleanly.

Scope:

- Add coarse failure category assignment:
  - `retrieval_miss`
  - `citation_miss`
  - `answer_incomplete`
  - `no_answer_wrong`
  - `timeout`
  - `unknown`
- Add `answer_lite` as an accepted mode.
- In first pass, `answer_lite` may run generation with judge disabled.
- Score what can be scored without judge:
  - expected points when deterministic checks exist
  - citation hit rate
  - no-answer correctness
  - groundedness when already available
- Include failure categories in per-case output and summary counts.

Not doing:

- No manual correction UI.
- No fine-grained rerank/context attribution unless already available.
- No judge cache yet.

Acceptance:

- Failed cases are grouped by coarse reason.
- `answer_lite` has a distinct behavior from `full`.
- Reports make it obvious whether the failure is likely retrieval-side or answer-side.

### Iteration 5: Judge Cache

Goal: reduce repeated LLM judge cost for unchanged answers.

Scope:

- Add judge result cache.
- Cache key:
  - case id
  - normalized answer
  - expected answer / expected points
  - judge model
  - rubric version
- Store whether a judge result was fresh or cached.
- Reuse cache in `answer_lite` and `full`.
- Never cache retrieval metrics.

Not doing:

- No distributed cache.
- No automatic baseline acceptance.

Acceptance:

- Re-running the same answer can reuse judge output.
- Changing the answer or rubric invalidates cache.
- Reports show judge cache hit/miss.

### Iteration 6: Limited Concurrency And Baseline Delta

Goal: make larger golden sets practical and compare results against an accepted baseline.

Scope:

- Add conservative concurrency settings.
- Retrieval-only can use higher concurrency than generation/judge.
- Per-case timeout should not fail the whole run.
- Store accepted baseline summary.
- Compare current run with baseline by mode and flavor.
- Show deltas for:
  - `Hit@10`
  - citation hit rate
  - answer pass rate
  - p95 latency
  - timeout count

Not doing:

- No scheduled/nightly runner.
- No parameter sweep.
- No A/B framework.

Acceptance:

- Wall-clock time improves without hiding case-level failures.
- Baseline delta is visible in summary output.
- Regressions in quality or latency are easy to spot.

### Iteration 7: Fine-Grained Failure Classification

Goal: improve failure categories enough to guide the next debugging action.

Scope:

- Keep the existing coarse categories.
- Add best-effort fine-grained categories:
  - `rerank_drop`
  - `context_loss`
  - `answer_unsupported`
  - `judge_uncertain`
- Count multiple categories independently.
- Add terminal/API/UI labels for the new categories.
- Add unit tests for category derivation.

Not doing:

- No manual correction UI.
- No new retrieval trace instrumentation unless an existing field is already
  available.
- No claim-level attribution.

Acceptance:

- Existing coarse categories still work.
- New categories appear only when supported by row evidence.
- Summary counts and case previews expose the new categories.

### Iteration 8: Eval Result Detail API

Status: implemented.

Goal: make full case diagnostics available without bloating status polling.

Scope:

- Add a backend endpoint to read one result row from the latest eval result file:
  - `GET /admin/eval/result/{case_id}`
- Return the existing result row schema with light normalization for UI safety.
- Include enough fields for the detail drawer:
  - expected points/docs/chunks
  - actual answer/citations
  - rerank/retrieval results
  - hit flags
  - judge fields
  - trace
  - error/timeout
- Keep `GET /admin/eval/status` compact.

Not doing:

- No historical run selector.
- No arbitrary file browsing.
- No result mutation.

Acceptance:

- Given a failed case id from `results_preview`, the UI/API can fetch its full
  result row.
- Missing or stale result files return a clear 404/400.
- Status polling payload remains small.

### Iteration 9: Reusable Eval Diagnostics UI

Status: implemented.

Goal: add the minimum report UI while keeping components reusable.

Scope:

- Add `EvalCaseTable.vue`.
- Add `EvalCaseDetailDrawer.vue`.
- Show failed/warning cases for the latest run.
- Filter by failure category and retrieval flavor.
- Open case detail drawer from a table row.
- Display:
  - question
  - score/status/categories
  - expected points/docs/chunks
  - actual answer/citations
  - top rerank/retrieval results
  - hit flags
  - judge result/cache status
  - trace latency/error

Not doing:

- No historical run list.
- No previous-run comparison UI.
- No charts.
- No manual annotation.
- No full chunk text highlighting.

Acceptance:

- A failed eval run can be diagnosed from the UI without opening JSONL.
- The table and drawer are not tightly coupled to `EvalRunPanel.vue`.
- The same components can later be reused for history, baseline, or feedback views.

## Recommended Cut Line

P1 should end after Iteration 3.

At that point:

- `quick` is usable.
- `retrieval_only` is usable.
- `full` still works.
- Admin can choose mode.
- Run summaries exist.

P2 starts at Iteration 4.

If time gets tight, stop after Iteration 3 and use the new loop for a while before investing in cache, concurrency, and richer reports.
