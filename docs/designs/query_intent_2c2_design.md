# Query-Intent Routing 2C-2 — Inline Shadow (dark wiring)

**Date:** 2026-06-13
**Status:** Spec — approved design, pending implementation plan.
**Roadmap:** `query_intent_routing_roadmap.md` → Stage 2C-2.
**Depends on:** 2A (deterministic intent + shadow plumbing, shipped), 2B (inline-ready LLM
classifier + merge, shipped), 2C-1 (golden correctness, all gates green 2026-06-13).

## Purpose

Move the intent classifier from **offline replay** to **inline on the live request path**, behind
two orthogonal flags, while emitting a **byte-for-byte 2A `query_plan`**. This stage answers one
question: *"can the classifier run inline safely under real latency and failure, and what exactly
would flip, while still inert?"* It produces the production-shadow evidence that gates the 2C-3
activation flip. It is **not** a behavior change — correctness against labels was already proven in
2C-1; 2C-2 proves operational safety and surfaces the would-be flips for human audit.

> **Governing invariant (shared with Design 1/2):** Classify intent once. Apply user policy once.
> Derive execution once. Trace all three separately.

## Decisions locked during brainstorming

- **Execution = full-traffic, synchronous inline.** No sample-rate knob. Rationale: the
  deterministic-only path is slated for deletion in the 2D cleanup, so the classifier is becoming
  the permanent path anyway; a sampling knob would be throwaway machinery (YAGNI), and inline cost
  is acceptable at the system's QPS.
- **Evidence = Option A:** extend the already-persisted `routing_trace` (it lands in
  `query_run_stats` every query) with inline-shadow fields + an offline aggregator script. No new
  table, no migration. Plus cheap WARN-level counters for classifier error/timeout as the kill
  switch's eyes. Chosen over a dedicated shadow table (second write path, breaks single-source-of-
  truth with feedback/quality, more to unwind at cleanup) and over live-counters-only (no per-query
  auditability, can't re-score history, loses correlation with result quality).
- **Seam = planner-local, no new graph node.** It remains one synchronous call feeding the plan; a
  dedicated `intent_classify` node is ceremony without payoff (consistent with the 2A decision).

## Architecture

All changes land in `backend/app/rag/query/planner.py` (`_resolve_routing`, `query_plan_node`) plus
the trace builder in `control/routing.py`. The resolution flow:

A **routing bundle** is the triple `(intent, decision, budget)` — the three things that must stay
mutually consistent because `_plan_from_routing` derives `prompt_policy`/`budget.reason` from the
*decision* and the budget is resolved from the *intent*. The gate selects a whole bundle, never a
loose decision.

```
det_bundle = (det, *route_for_intent(det, breadth, cfg))                    (always; authoritative
                                                                            entity_scope + safe-default floor)

if intent.inline_enabled:                                                   (full traffic, synchronous)
    result  = classify_intent_inline(query, det)      (envelope: markers|None, reason, latency_ms)
    merged  = merge_intent(det, result.markers)       (fallback_used when markers is None)
    merged_bundle = (merged, *route_for_intent(merged, breadth, cfg))
    gated_bundle  = trust_gate_bundle(merged_bundle, det_bundle)            (merged bundle iff
                                                                            activatable(merged),
                                                                            else det_bundle)
    inline_shadow = build_inline_shadow(result, merged_bundle, det_bundle)  (records raw proposal vs det)
else:
    merged, gated_bundle, inline_shadow = det, det_bundle, INACTIVE         (classifier never runs)

emitted_bundle = gated_bundle if intent.active_mode else det_bundle         (the dark-wiring branch)
emitted_intent, emitted_decision, emitted_budget = emitted_bundle
plan = _plan_from_routing(flavor, breadth, emitted_decision, emitted_budget, cfg)
```

**One activation predicate, used by both the gate and the shadow:**

```
activatable(intent) = intent.confidence == "high" and not intent.fallback_used
```

The `not fallback_used` guard matters: `merge_intent(det, None)` *preserves* the deterministic
confidence (`inferred.py:84`), so a classifier failure on an already-`high` deterministic case would
otherwise produce a merged bundle with `confidence == "high"` and `fallback_used == True` — and the
gate would "activate" it, surfacing `fallback_used` in the top-level emitted intent. A failed
classifier must **never** drive, so `activatable` excludes fallbacks.

**The whole bundle is selected together, so intent, decision, and budget never disagree.**
`trust_gate_bundle(merged_bundle, det_bundle)` returns the **merged** bundle iff `activatable(merged)`,
else the **deterministic** bundle. Two consequences:

1. *Budget tracks decision* (Finding 1): a merged-intent route can't inherit the deterministic
   budget — they come from the same bundle. Without this, a synthesis/discovery route would get a
   mismatched `budget`, `budget.reason`, and (via `decision.prompt_variant`) `prompt_policy`.
2. *Intent tracks decision* (Finding 2): on fallback or low/medium confidence, the emitted **bundle
   is the pristine deterministic one** — so top-level `routing_trace.intent` is deterministic exactly
   when the emitted decision is, never a `fallback_used` artifact. The merged proposal is *only* in
   `inline_shadow`; it reaches the top-level trace solely when it wins the gate (`activatable` and
   `active_mode`).

`route_for_intent(intent, breadth, cfg)` denotes the per-intent budget+derive step the planner
*already* performs for the deterministic route (`resolve_budget_profile` → `derive_routing_decision`,
`planner.py:92-93`), returning the `(decision, budget)` pair (the bundle prepends `intent`). 2C-2
factors it into a small **planner-local** helper so deterministic and merged routes resolve
identically. It is **not** an import from `control/route_scoring.py` — that module is offline scoring
and must not be pulled into the live path; if a single shared helper is wanted, it moves to
`control/routing.py` and both the planner and the scorer import it from there.

### Two flags (both default off)

The flags are **operational kill switches**, so they live in `runtime_settings`
(`app/core/runtime_settings.py` — SQLite-backed, in-memory cache, flipped instantly via the settings
API with **no process restart**), read in the sync planner path via `get_cached`. Keys
`intent.inline_enabled` / `intent.active_mode`, default `"false"`. This is deliberately distinct from
the classifier *tuning* params (`INTENT_CLASSIFIER_MODEL`, `_TIMEOUT`, `_TEMPERATURE`,
`_MAX_TOKENS`), which stay in env-backed pydantic `Settings` where a restart is acceptable. Putting
the kill switch in env `Settings` would make "no deploy" false; putting it in `runtime_settings`
makes the instant flip real.

**The two keys are registered in `_DEFAULTS`** (`runtime_settings.py:10`), not left to falsy-by-
absence. Today `_DEFAULTS` is generated purely from `QueryConfig`; 2C-2 adds two static entries
(`"intent.inline_enabled": "false"`, `"intent.active_mode": "false"`). This makes them visible to the
settings API and the report before any first write, and gives `get_cached` a real default. A small
helper `_intent_flag(key) -> bool` does the `"true"/"false"` string→bool read so the planner doesn't
parse strings inline.

| Flag (runtime_settings key) | Meaning | Role |
| --- | --- | --- |
| `intent.inline_enabled` | does the classifier run live at all | **kill switch** — off ⇒ zero added latency/cost, identical to 2A today |
| `intent.active_mode` | may the gated result drive `query_plan` | **flip point** for 2C-3 |

### Flag truth table

| INLINE | ACTIVE | Behavior |
| --- | --- | --- |
| off | off | 2A today — deterministic only, classifier dark. Kill-switch resting state. |
| **on** | **off** | **2C-2 dark launch** — classifier runs full-traffic, merge+gate computed and traced, `emitted_decision = det_decision`. **Byte-for-byte 2A plan.** |
| on | on | 2C-3 — gated result drives. First behavior change. |
| off | on | Inert (no classifier ran ⇒ `gated == det_decision`); harmless, unused. |

### Load-bearing invariant

In the `(on, off)` state the emitted `query_plan` is **byte-for-byte identical** to `(off, off)`.
The classifier runs and is observed, but the plan never reads `gated`. This is the testable
guarantee that earns "ships dark" (preservation test below).

## Failure, latency & kill switch

The inline call runs full-traffic synchronously, so its failure surface is a live concern even
while inert (a hang would delay every plan). Three layers:

1. **Tight inline timeout via a dedicated setting.** Today `classify_intent_llm` honors
   `INTENT_CLASSIFIER_TIMEOUT` (`30s`, a replay-era value used by the offline scorer/replay, which
   should keep a generous budget so batch runs aren't skewed by spurious timeouts). 2C-2 adds a
   separate `INTENT_CLASSIFIER_INLINE_TIMEOUT` (`6s`) used **only** by the inline wrapper — blocking
   the request path for 30s is unacceptable. The offline `INTENT_CLASSIFIER_TIMEOUT` is left at 30s.
2. **Failure → deterministic fallback via a result envelope over a shared raw seam.**
   `classify_intent_llm` currently catches *every* exception and parse failure into a bare `None`
   (`llm_classifier.py:38`), so a wrapper around it **cannot** recover the reason — the information is
   already lost inside the `except`. So 2C-2 factors out the raw seam rather than wrapping the lossy
   function:
   - `_invoke_classifier(query, det, timeout) -> str` — builds the `ChatOpenAI` client and invokes
     it, returning the raw response content. It does **not** catch; timeout/transport exceptions
     propagate.
   - `classify_intent_inline(query, det) -> ClassifyResult` owns the try/except and the taxonomy:
     `_is_timeout(exc)` → `"timeout"`, any other exception → `"error"`, a successful call whose body
     fails `parse_llm_markers` → `"parse_fail"`, success → `"none"`. It times the call and applies
     `_calibrate_confidence`. Envelope:
     `ClassifyResult(markers: LlmMarkers | None, fallback_reason: str, latency_ms: int)`.
   - `_is_timeout(exc)` recognizes the real provider/client timeout types, not just builtin
     `TimeoutError` — `openai.APITimeoutError`, `httpx.TimeoutException`, `concurrent.futures.TimeoutError`
     (matched defensively by class name to avoid hard imports), falling through to `"error"` otherwise.
     The plan includes a unit test asserting each of these classifies as `"timeout"`.
   - `classify_intent_llm` is **refactored to delegate** to `_invoke_classifier` + `parse_llm_markers`
     + `_calibrate_confidence` inside its existing `except → None`, so it keeps its `-> LlmMarkers |
     None` contract and the offline scorer/replay are unchanged, while sharing one invoke/parse seam
     with the inline path (no duplicated ChatOpenAI construction).

   `merge_intent(det, result.markers)` returns the deterministic intent with `fallback_used=True`
   whenever `markers is None`. A classifier failure degrades to the exact 2A route — never an
   exception into the request path.
3. **Kill switch = `intent.inline_enabled=false`.** Skips the wrapper call entirely — instant removal
   of added latency/cost, back to 2A resting state, no restart (runtime_settings flip).
4. **WARN counters (kill switch's eyes).** On every fallback path emit a structured WARN with
   `fallback_reason` (`timeout` / `error` / `parse_fail`) and measured `latency_ms`. Ops see
   misbehavior without running the offline script. Cheap log lines, not a metrics backend.

**Cost:** even inert, full traffic pays one LLM call per query. Accepted (low QPS + impending
cleanup). The tight timeout bounds worst-case latency; the kill switch bounds blast radius.

## Trace & evidence (Option A)

### Trace extension

`build_routing_trace` already records `routing_decision` (emitted route) and a `shadow_routing`
block (currently a degenerate self-comparison because `would_be = trust_gate(inferred, decision,
decision)`). 2C-2 makes the shadow real and adds inline-observability under a single `inline_shadow`
key:

```json
"inline_shadow": {
  "ran": true,
  "fallback_used": false,
  "fallback_reason": "none",
  "latency_ms": 412,
  "confidence": "high",
  "merged_markers": { "needs_synthesis": true, "needs_discovery": false, "needs_multi_hop": false },
  "merged_reasons": ["llm:implicit comparison across entities"],
  "merged_source": "llm",
  "proposal_execution": { "...merged-bundle route execution dict (raw LLM proposal, pre-gate)..." },
  "proposal_diverged": true,
  "activatable_diverged": true
}
```

- **Top-level `routing_trace.intent` is the *emitted bundle's* intent.** Because the gate selects a
  whole bundle, the top-level intent always matches the emitted decision/budget. In 2C-2
  (`active_mode=false`) the emitted bundle is the deterministic one, so the top-level intent/decision
  fields are byte-for-byte 2A. The merged would-be view (markers, reasons, source, confidence) lives
  **inside** `inline_shadow` for audit. When `active_mode` flips at 2C-3, the top-level intent
  becomes the **gated** bundle's intent — which is the merged intent *only when*
  `confidence == "high"`, and otherwise still the deterministic intent (the gate fell back). So even
  post-flip, top-level intent never shows an un-activated merged proposal. `query_plan` byte-for-byte
  stability is asserted only for the 2C-2 `(on, off)` state, not across the 2C-3 flip.
- `proposal_execution` — the execution dict of the **merged bundle's** decision, i.e. the **raw LLM
  proposal route, before the gate**. This is deliberately pre-gate so the shadow can record *all*
  proposal divergence, including low/medium-confidence proposals the gate would reject.
- `proposal_diverged` — `proposal_execution != det execution`, using the existing normalized
  execution-field comparison (`decision_execution_dict`), not reasons/vetoes. Can be true at any
  confidence (this is what makes a "diverged-low, not activatable" case representable).
- `activatable_diverged` — `proposal_diverged AND activatable(merged)` (i.e. `confidence == "high"`
  and not `fallback_used`). The headline: exactly the queries whose route changes the moment
  `active_mode` flips. `proposal_diverged && !activatable_diverged` is the safe, non-activating
  divergence bucket.
- `fallback_reason` ∈ `none | timeout | error | parse_fail` (from the `ClassifyResult` envelope).
- When `intent.inline_enabled=false`: `ran=false`, `fallback_reason="none"`, and the
  merged/comparison fields are omitted/null.

This block rides the existing `routing_trace` persistence into `query_run_stats`
(`query_observability.py` already writes `routing_trace`). **No migration.**

### Offline report

`backend/scripts/report_inline_shadow.py` (standalone, archived after the flip — never imported by
live code) reads `query_run_stats` over a window and prints the **2C-3 go/no-go gate**:

| Metric | Gate |
| --- | --- |
| `classifier_error_rate` (incl. timeout) | ≤ 1% |
| `latency_ms` p95 | ≤ inline budget (6000 ms) |
| `fallback_rate` | reported (context, not a hard gate) |
| `activatable_divergence_rate` | reported + **manual audit** of the would-be flips |
| observed volume | ≥ 200 queries before the gate is meaningful |

The gate is **stability + inspectability**, not re-deriving correctness (that was 2C-1). The human
reviews the `activatable_diverged` rows before 2C-3.

## The excisable seam (designing for 2D)

The 2D-deletable scaffolding is named and co-located so removal is one cut:

- **One gating function** `_inline_intent(query, det_bundle, breadth, cfg) -> (gated_bundle,
  inline_shadow)` holds the entire dark-wiring surface: the `intent.inline_enabled` check, classifier
  call, merge, `trust_gate_bundle`, and the `inline_shadow` block. `query_plan_node` calls it, then
  `emitted_bundle = gated_bundle if intent.active_mode else det_bundle`.
- **2D deletion is mechanical:** drop both flag reads, make `_inline_intent` unconditional (rename to
  the permanent classifier step), set `emitted_bundle = gated_bundle` always, delete
  `proposal_diverged`/`activatable_diverged`/`proposal_execution` (degenerate once `gated_bundle` *is*
  the plan). What remains is the permanent residue: inline classifier + merge + gate +
  `latency_ms`/`fallback` telemetry + WARN counters.
- **No proposal/shadow logic leaks** into `_plan_from_routing` or downstream nodes — they only ever
  see the single `emitted_bundle`. That containment is what makes the cut clean.

### What survives 2D vs what's scaffolding

| Piece | After 2D |
| --- | --- |
| inline `classify_intent_llm` + `merge_intent` + `trust_gate` | permanent — *the* routing path |
| deterministic `infer_signals` | permanent but demoted — authoritative `entity_scope` + safe-default/fallback target |
| `latency_ms`, `fallback_reason`, `fallback_used` | permanent telemetry |
| error/latency WARN counters | permanent |
| `intent.inline_enabled` (runtime_settings) | deleted (classifier always runs) |
| `intent.active_mode` (runtime_settings) | deleted (or collapses to a plain kill switch) |
| `INTENT_CLASSIFIER_INLINE_TIMEOUT` (env) | permanent — the inline budget |
| `proposal_execution` / `proposal_diverged` / `activatable_diverged` | deleted (degenerate) |
| `scripts/report_inline_shadow.py` | archived |

## Testing

1. **Byte-for-byte preservation (core guarantee).** Parametrized over a query fixture: emitted
   `query_plan` dict is identical between `(inline=off, active=off)` and `(inline=on, active=off)`,
   with `classify_intent_inline` stubbed to return a **divergent high-confidence** route (markers
   that flip both the decision *and* the budget, exercising the paired-budget path). Proves even a
   would-flip case does not change the plan while inert.
2. **Active-mode wiring.** Same divergent stub, `(inline=on, active=on)`: emitted plan equals the
   gated route **and** the emitted `budget` equals the merged budget (guards the Finding-1 mismatch).
   Guards against a dead branch 2C-3 would discover too late.
3. **Failure → deterministic fallback.** Stub `classify_intent_inline` to return each
   `fallback_reason` (`timeout`/`error`/`parse_fail`): no exception escapes, `fallback_used=True`,
   `inline_shadow.fallback_reason` set correctly, plan equals the deterministic route in both active
   states. **Include the `det.confidence=="high"` fallback case** (Finding 2): assert
   `activatable(merged)` is false and the emitted bundle is the pristine `det_bundle` — a failed
   classifier never activates even when deterministic confidence was high.
4. **Trace fields.** Assert `inline_shadow.ran/proposal_diverged/activatable_diverged/latency_ms` and
   the `merged_*` audit fields across: diverged-high (`proposal_diverged && activatable_diverged`),
   diverged-low (`proposal_diverged && !activatable_diverged` — proposal differs but confidence
   medium/low), and converged (`!proposal_diverged`) cases.
5. **Kill switch.** `(inline=off)`: `classify_intent_inline` is **not called** (mock asserts zero
   calls), `inline_shadow.ran=false`, `fallback_reason="none"`.
6. **Offline report unit.** Synthetic `query_run_stats` rows → aggregator; assert error rate, p95
   latency, activatable-divergence rate compute correctly (same pattern as 2C-1's `aggregate` test).

All real LLM stubbed; zero network in the suite. The script's live run against actual
`query_run_stats` is a manual final task in the implementation plan, like 2C-1's scorer run.

## Out of scope (deferred)

- **The flip itself** — flipping `intent.active_mode` to drive routing is 2C-3, gated on this
  stage's shadow report + the 2C-1 correctness gates.
- **Discovery retirement** — 2D.
- **Per-dimension confidence, continuous score** — deferred per roadmap.
- **`requested_format`** — stays `null` until a later stage.
