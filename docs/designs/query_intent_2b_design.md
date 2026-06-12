# Design 2B — Hybrid LLM Classifier (offline-replay shadow)

**Date:** 2026-06-12
**Status:** Proposed
**Roadmap:** `query_intent_routing_roadmap.md` (Design 2, Stage B of A/B/C).
**Depends on:** `query_intent_2a_design.md` (2A — graded confidence + shadow routing) — shipped.

Stage 2B builds the **real, reusable** temp-0 LLM intent classifier and its merge logic, and
validates them by **offline replay** over logged queries. It adds the input source that 2C will
later wire inline. **No live-path change; zero production latency or cost on requests.**

It answers **"does LLM escalation improve intent classification enough to matter?"** — a
*measurement*. It does **not** answer "are the changes correct?" or "can it drive routing?" —
those are 2C, which has the labeled routing golden set.

> **Governing invariant (shared):** Classify intent once. Apply user policy once. Derive
> execution once. Trace all three separately.

---

## 1. Scope & the measure-not-judge boundary

2B adds three things, all exercised **offline only**:
1. a temp-0 LLM classifier for the fuzzy marker dimensions,
2. a merge that combines LLM markers with the deterministic (authoritative) `entity_scope`,
3. an offline replay harness over `query_run_stats` that produces disagreement/divergence metrics.

**Boundary:** 2B reports *rates and disagreements*; it never claims a change is *right*. Correctness
requires labeled expected routes — the 2C routing golden set. So 2B's deliverable is evidence
(*how often, and how impactfully, would escalation change things*), and the go/no-go into 2C rests
on that evidence.

**Live invariant:** 2B touches no request-path code. The golden set must still match the accepted
Design 1 baseline (it is unaffected — nothing inline changed).

The classifier and merge built here are **production-ready units**, not throwaway scripting — 2C
wires the same functions inline behind the trust gate. Only their *exercise* in 2B is offline.

---

## 2. The classifier — `classify_intent_llm`

Reuses the project's existing LLM-call pattern (as in `groundedness.py` / `hyde_search.py`):

```python
def classify_intent_llm(query: str, deterministic: InferredSignals) -> LlmMarkers | None:
    ...  # returns parsed markers, or None on any error/timeout/parse-fail
```

- **Model / params (settings in `backend/app/config.py`):** `INTENT_CLASSIFIER_MODEL` defaults to
  `""` and is resolved at the call site as `settings.INTENT_CLASSIFIER_MODEL or settings.CHAT_MODEL`
  (don't default one settings field to another inside the `Settings` class). Plus
  `INTENT_CLASSIFIER_TEMPERATURE = 0.0`, bounded `INTENT_CLASSIFIER_MAX_TOKENS`,
  `INTENT_CLASSIFIER_TIMEOUT` — same settings shape as HyDE/groundedness.
- **Strict JSON schema** (the LLM output contract):
  ```json
  { "needs_synthesis": true, "needs_discovery": false,
    "confidence": "high|medium|low", "reasons": ["..."] }
  ```
  `requested_format` is **out of scope** in 2B (presentation, not routing — deferred). `entity_scope`
  is **not** asked of the LLM (§3).
- **Robust parse:** **extract the shared strict→fenced→stripped algorithm** currently inside
  groundedness's private `_parse_groundedness` into a small shared util. Keep a generic
  `parse_llm_json(raw) -> Any | None` for groundedness compatibility and expose
  `parse_llm_json_object(raw) -> dict | None` for the classifier — do **not** import the private
  `_parse_groundedness`. Then validate the classifier shape (booleans + enum) before returning;
  anything off-contract → treat as parse-fail.
- **Failure handling:** any exception / timeout / parse-fail / schema-violation → return `None`.
  The merge (§3) turns `None` into a clean deterministic fallback. The classifier never raises to
  its caller.

`LlmMarkers` is a small frozen dataclass: `needs_synthesis: bool`, `needs_discovery: bool`,
`confidence: Confidence` (reuse the existing `Confidence` alias from `control/inferred.py`, not
plain `str`), `reasons: list[str]`.

### Prompt shape
A short role/task block + the compact schema + minimal rules: "Classify the *routing intent* of a
Chinese/English enterprise-document question. Decide whether it needs cross-entity/temporal
**synthesis** (comparison, relationship, 'difference between') and whether it needs **discovery**
(finding which entities/people relate to something). Output strict JSON only." 2-3 few-shot
examples covering an implicit comparison (no `比较` keyword), an implicit discovery (no `哪些`
keyword), and a plain lookup (neither). Temp 0, so examples anchor the contract.

---

## 3. Merge semantics — `merge_intent`

```python
def merge_intent(deterministic: InferredSignals, llm: LlmMarkers | None) -> InferredSignals:
    ...
```

- **`entity_scope`** ← deterministic, untouched (authoritative entity-linking grounding; the LLM
  has no entity table and is never asked for it).
- **`needs_synthesis`, `needs_discovery`** ← monotonic merge: deterministic-positive markers are
  sticky, and the LLM may only add missing markers (`deterministic OR llm`). On fallback the
  deterministic markers are preserved unchanged. This protects high-precision keyword/control cases
  from high-confidence LLM erasure while still allowing 2B to recover implicit markers.
- **`needs_multi_hop`** ← **re-derived** from `(deterministic entity_scope, merged needs_discovery)`
  using the exact existing rule (`scope ∈ {broad, none} AND needs_discovery`). "Derive once",
  better input — not taken from the LLM directly.
- **`confidence`** ← LLM when it ran; deterministic on fallback.
- **`source`** = `"llm_escalated"` when the LLM ran and parsed; `"deterministic"` on fallback.
- **`fallback_used`** = `True` when `llm is None` (error/timeout/parse-fail), else `False`.
- **`reasons`** = deterministic reasons + LLM reasons (tagged), so provenance is inspectable.

On fallback (`llm is None`) the result is the deterministic intent verbatim except
`fallback_used=True` — i.e., escalation that fails costs nothing and changes nothing.

---

## 4. Replay harness — `replay_intent_classifier.py`

A script under `backend/scripts/` mirroring `eval_golden_set.py` (CLI, concurrency, JSONL output).

**Source-of-truth table — reconstruct from the logged row; do NOT recompute from current code:**

| Replay input | Source (per `query_run_stats` row) |
|---|---|
| query text | `query` column |
| `entity_mode`, `selected_entities` | `settings_json` root fields |
| deterministic intent (`entity_scope`, markers, `confidence`) | `settings_json.routing_trace.intent` |
| **baseline** `logged_design1_decision` | `settings_json.routing_trace.routing_decision` — **the logged Design 1 decision, not recomputed** |
| raw infra `enable_hyde / enable_query_expansion / enable_multi_hop` | `settings_json.routing_trace.infra` — **not** top-level `resolved_settings.use_*` (those are *effective* plan outputs; a deterministic query that didn't need multi-hop logs `use_multi_hop=false` even when `cfg.use_multi_hop` was on, which would wrongly veto an LLM discovery flip in replay) |
| `retrieval_breadth`, `strict_evidence` | `settings_json.routing_trace.policy` |

Rows without a `routing_trace` (pre-2A) are **skipped** and counted (coverage metric §5).

**Replayed bucket (explicit):** rows with deterministic `confidence ∈ {medium, low}` are **always**
replayed; a bounded random sample of `high`-confidence rows is replayed as a **control**; all other
`high` rows are **skipped** (counted in coverage). No live row is ever escalated on the request path
— replay is entirely offline.

**Per row:**
1. `llm = classify_intent_llm(query, deterministic_intent)`.
2. `merged = merge_intent(deterministic_intent, llm)`.
3. Reconstruct a replay `QueryConfig`: behavioral flags from the **logged trace** —
   `use_hyde / use_query_expansion / use_multi_hop ← infra.enable_*`,
   `strict_evidence ← policy.strict_evidence`, and a `retrieval_flavor` consistent with
   `policy.retrieval_breadth`; numeric budget params (`search_limit`, `rrf_max_results`,
   `rerank_max_top_k`, `hyde_limit`) from the **current** stable `QueryConfig` defaults (global, not
   per-query — budget tiers are stable config).
4. `budget = resolve_budget_profile(breadth, merged.entity_scope, merged.needs_synthesis, replay_cfg)`.
5. `merged_decision = derive_routing_decision(merged, breadth, replay_cfg, budget_reason=budget.reason)`.
6. `diverged = execution_fields(merged_decision) != execution_fields(logged_design1_decision)`
   (same field subset as the routing `decision_execution_dict`, extracted from the logged decision
   dict); `activatable = llm is not None and diverged and merged.confidence == "high"` — fallback
   rows remain deterministic and are never candidates for 2C activation.

**Concurrency / cost controls:** `--limit`, `--concurrency`, `--delay`, `--high-sample-size`, `--since`.

### Artifacts (mirror `eval_golden_set`)
- `data/intent_2b_replay_<date>.jsonl` — per query: `{ query, entity_scope, det_markers,
  llm_markers, merged, fallback_used, det_decision, merged_decision, diverged, activatable }`.
- `data/intent_2b_replay_<date>_summary.json` — the §5 rates.

---

## 5. Metrics

All descriptive (correctness is 2C):

| Metric | Definition |
|---|---|
| Per-dimension disagreement rate | LLM vs deterministic on `needs_synthesis`, `needs_discovery`, and re-derived `needs_multi_hop` |
| Confidence-lift rate | fraction where LLM raises a `medium`/`low` to `high` (would un-gate the trust gate in 2C) |
| Shadow-divergence rate | fraction where the merged-intent routing decision differs from Design 1 (execution-field comparison) |
| **Activatable-divergence rate** | **divergences at LLM-`high` confidence — the routes that would actually drive once 2C flips the gate. The headline sizing signal.** |
| Fallback rate | LLM error/timeout/parse-fail → deterministic |
| Replay coverage / skipped-row rate | replayed rows vs total candidate rows (and why rows were skipped: no `routing_trace`, unsampled `high`) |
| High-control activatable-divergence rate | activatable-divergence within the `high` control sample — should be low; a high value flags an over-eager LLM or a deterministic-`high` mis-bucketing |

Break each down by the deterministic bucket (`medium` vs `low`) and report the `high`-control
sample separately.

**Readiness gates named in 2B are *operational only* — not correctness gates** (correctness needs
labels, which arrive in 2C). The pre-2C operational gates are: (a) **replay coverage** is sufficient
(enough escalation-bucket rows actually classified); (b) **fallback / parse-fail rate** is under a
cap (the classifier is reliable enough to be worth wiring); (c) **high-control agreement** is not
alarming (the LLM isn't randomly diverging on easy cases). The **activatable-divergence rate** is the
headline *sizing* signal — "how much would change" — **not proof the changes are correct.** That
proof is 2C's job.

---

## 6. Components & boundaries

| Unit | Responsibility | Where |
|---|---|---|
| `classify_intent_llm` | query → `LlmMarkers` (strict JSON, temp 0, never raises) | `backend/app/rag/query/control/llm_classifier.py` (new) |
| `LlmMarkers` | frozen dataclass of the LLM output contract (`confidence: Confidence`) | same file |
| `merge_intent` | deterministic scope + LLM markers → `InferredSignals` | `backend/app/rag/query/control/inferred.py` |
| `parse_llm_json` / `parse_llm_json_object` | shared strict→fenced→stripped JSON extractor plus object-only wrapper | small shared util; groundedness uses generic, classifier uses object-only |
| `replay_intent_classifier.py` | offline corpus replay → artifacts | `backend/scripts/` |
| settings | `INTENT_CLASSIFIER_MODEL / _TEMPERATURE / _MAX_TOKENS / _TIMEOUT` | `backend/app/config.py` (`Settings`) |

`classify_intent_llm` and `merge_intent` are pure/isolated and **unit-tested with a mocked LLM**:
clean JSON, fenced JSON, garbage → fallback, timeout → fallback, schema-violation → fallback, and a
marker flip (`needs_discovery` false→true on a `none`-scope query) correctly flips re-derived
`needs_multi_hop`. The replay script is integration-run, not unit-asserted.

---

## 7. Acceptance

- **Live path unchanged:** 2B adds no request-path code; golden-set retrieval-only + full still
  match the accepted Design 1 baseline. The shared parser refactor is behavior-preserving —
  existing groundedness parser tests still pass against the extracted helper.
- **Unit tests green:** classifier (all parse/fallback paths) + merge (ownership, re-derivation,
  fallback provenance) + the shared parser helper.
- **Replay produces evidence:** one replay run over a recent `query_run_stats` window yields the
  artifacts and a readable summary; the **activatable-divergence rate** and per-dimension
  disagreement profile are the *sizing* evidence carried into the 2C go/no-go review, gated by the
  §5 **operational** readiness checks (coverage, fallback/parse-fail under cap, high-control not
  alarming). Correctness is not asserted in 2B.

---

## 8. Non-goals

- No live/inline escalation, no trust-gate activation (2C).
- No routing golden set, no labels, no correctness scoring (2C).
- No `requested_format` extraction.
- No discovery retirement, no new graph node, no `InferredSignals`→`QueryIntent` rename.
- No retuning of model temperature/token settings elsewhere (`9e43b2c`).
