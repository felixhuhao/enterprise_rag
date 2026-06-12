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

- **Model / params:** `settings.INTENT_CLASSIFIER_MODEL` (defaults to `settings.CHAT_MODEL`),
  `INTENT_CLASSIFIER_TEMPERATURE = 0`, bounded `INTENT_CLASSIFIER_MAX_TOKENS`,
  `INTENT_CLASSIFIER_TIMEOUT` — same settings shape as HyDE/groundedness.
- **Strict JSON schema** (the LLM output contract):
  ```json
  { "needs_synthesis": true, "needs_discovery": false,
    "confidence": "high|medium|low", "reasons": ["..."] }
  ```
  `requested_format` is **out of scope** in 2B (presentation, not routing — deferred). `entity_scope`
  is **not** asked of the LLM (§3).
- **Robust parse:** reuse groundedness's strict→fenced→stripped JSON extraction. Validate the
  shape (booleans + enum) before returning; anything off-contract → treat as parse-fail.
- **Failure handling:** any exception / timeout / parse-fail / schema-violation → return `None`.
  The merge (§3) turns `None` into a clean deterministic fallback. The classifier never raises to
  its caller.

`LlmMarkers` is a small frozen dataclass: `needs_synthesis: bool`, `needs_discovery: bool`,
`confidence: str`, `reasons: list[str]`.

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
- **`needs_synthesis`, `needs_discovery`** ← LLM when it ran; deterministic on fallback.
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

- **Corpus reconstruction:** read `query_run_stats` rows; from `query` (raw text) and `settings_json`
  recover `entity_mode`, `selected_entities`, and the logged deterministic `intent.confidence`. Skip
  rows lacking the needed fields. (No new live logging — 2A already persists all of this.)
- **Replayed bucket:** rows with `confidence ∈ {medium, low}` (the escalation bucket), **plus a
  bounded random sample of `high`-confidence rows** as a control (the LLM should mostly agree).
- **Per row:** run `classify_intent_llm` → `merge_intent` → `derive_routing_decision(merged, breadth,
  cfg)`; compare its `_decision_execution_dict` against the row's logged Design 1 decision.
- **Concurrency / cost controls:** `--limit`, `--concurrency`, `--delay`, `--high-sample-size`,
  `--since` (date filter). Deterministic-only rows are never escalated.

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
| **Activatable-divergence rate** | **divergences at LLM-`high` confidence — the routes that would actually drive once 2C flips the gate. The headline go/no-go number.** |
| Fallback rate | LLM error/timeout/parse-fail → deterministic |

Break each down by the deterministic bucket (`medium` vs `low`) and report the `high`-control
agreement rate separately.

---

## 6. Components & boundaries

| Unit | Responsibility | Where |
|---|---|---|
| `classify_intent_llm` | query → `LlmMarkers` (strict JSON, temp 0, never raises) | `backend/app/rag/query/control/llm_classifier.py` (new) |
| `LlmMarkers` | frozen dataclass of the LLM output contract | same file |
| `merge_intent` | deterministic scope + LLM markers → `InferredSignals` | `backend/app/rag/query/control/inferred.py` |
| `replay_intent_classifier.py` | offline corpus replay → artifacts | `backend/scripts/` |
| settings | `INTENT_CLASSIFIER_MODEL / _TEMPERATURE / _MAX_TOKENS / _TIMEOUT` | `backend/app/core/config` (settings) |

`classify_intent_llm` and `merge_intent` are pure/isolated and **unit-tested with a mocked LLM**:
clean JSON, fenced JSON, garbage → fallback, timeout → fallback, schema-violation → fallback, and a
marker flip (`needs_discovery` false→true on a `none`-scope query) correctly flips re-derived
`needs_multi_hop`. The replay script is integration-run, not unit-asserted.

---

## 7. Acceptance

- **Live path unchanged:** 2B adds no request-path code; golden-set retrieval-only + full still
  match the accepted Design 1 baseline.
- **Unit tests green:** classifier (all parse/fallback paths) + merge (ownership, re-derivation,
  fallback provenance).
- **Replay produces evidence:** one replay run over a recent `query_run_stats` window yields the
  artifacts and a readable summary; the **activatable-divergence rate** and per-dimension
  disagreement profile are the evidence carried into the 2C go/no-go review.

---

## 8. Non-goals

- No live/inline escalation, no trust-gate activation (2C).
- No routing golden set, no labels, no correctness scoring (2C).
- No `requested_format` extraction.
- No discovery retirement, no new graph node, no `InferredSignals`→`QueryIntent` rename.
- No retuning of model temperature/token settings elsewhere (`9e43b2c`).
