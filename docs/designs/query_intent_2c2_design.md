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

```
infer_signals(query, entity_mode, matched)        → det            (always)
det_decision = route_for_intent(det, breadth)                       (always; authoritative
                                                                     entity_scope + safe-default floor)

if INLINE_ENABLED:                                                  (full traffic, synchronous)
    llm     = classify_intent_llm(query, det)      (timeout→None)
    merged  = merge_intent(det, llm)               (fallback_used on None)
    merged_decision = route_for_intent(merged, breadth)
    gated   = trust_gate(merged, merged_decision, det_decision)     (real, not inert)
else:
    merged, gated = det, det_decision                              (classifier never runs)

emitted_decision = gated if ACTIVE_MODE else det_decision          (the dark-wiring branch)
plan = _plan_from_routing(..., emitted_decision, ...)
```

`route_for_intent(intent, breadth, cfg)` denotes the per-intent budget+derive step the planner
*already* performs for the deterministic route (`resolve_budget_profile` → `derive_routing_decision`,
`planner.py:92-93`). 2C-2 factors that into a small **planner-local** helper so the deterministic and
merged routes resolve identically. It is **not** an import from `control/route_scoring.py` — that
module is offline scoring and must not be pulled into the live path; if a single shared helper is
wanted, it moves to `control/routing.py` and both the planner and the scorer import it from there.

### Two flags (both default off)

| Flag | Meaning | Role |
| --- | --- | --- |
| `INTENT_CLASSIFIER_INLINE_ENABLED` | does the classifier run live at all | **kill switch** — off ⇒ zero added latency/cost, identical to 2A today |
| `INTENT_CLASSIFIER_ACTIVE_MODE` | may the gated result drive `query_plan` | **flip point** for 2C-3 |

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

1. **Timeout → deterministic fallback (exists).** `classify_intent_llm` already wraps the call in
   try/except and honors `INTENT_CLASSIFIER_TIMEOUT`. 2C-2 lowers the default from the replay-era
   `30s` to a tight inline budget (`INTENT_CLASSIFIER_TIMEOUT = 6`), unacceptable to block in-band
   for 30s. On timeout/error/parse-failure the classifier returns `None`; `merge_intent(det, None)`
   returns the deterministic intent with `fallback_used=True`. A classifier failure degrades to the
   exact 2A route — never an exception into the request path.
2. **Kill switch = `INLINE_ENABLED=false`.** Skips the classifier call entirely — instant removal of
   added latency/cost, back to 2A resting state, no deploy (settings flag).
3. **WARN counters (kill switch's eyes).** On every fallback path emit a structured WARN with
   `fallback_reason` (`timeout` / `error` / `parse_fail`) and measured `classifier_latency_ms`. Ops
   see misbehavior without running the offline script. Cheap log lines, not a metrics backend.

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
  "fallback_reason": null,
  "classifier_latency_ms": 412,
  "confidence": "high",
  "would_be_execution": { "...gated route execution dict..." },
  "diverged": true,
  "activatable_diverged": true
}
```

- `diverged` — `would_be_execution != det execution`, using the existing normalized
  execution-field comparison (`decision_execution_dict`), not reasons/vetoes.
- `activatable_diverged` — `diverged AND confidence == "high"`. The headline: these queries change
  behavior the moment `ACTIVE_MODE` flips.
- When `INLINE_ENABLED=false`: `ran=false` and the comparison fields are omitted/null.

This block rides the existing `routing_trace` persistence into `query_run_stats`
(`query_observability.py` already writes `routing_trace`). **No migration.**

### Offline report

`backend/scripts/report_inline_shadow.py` (standalone, archived after the flip — never imported by
live code) reads `query_run_stats` over a window and prints the **2C-3 go/no-go gate**:

| Metric | Gate |
| --- | --- |
| `classifier_error_rate` (incl. timeout) | ≤ 1% |
| `classifier_latency_ms` p95 | ≤ inline budget (6000 ms) |
| `fallback_rate` | reported (context, not a hard gate) |
| `activatable_divergence_rate` | reported + **manual audit** of the would-be flips |
| observed volume | ≥ 200 queries before the gate is meaningful |

The gate is **stability + inspectability**, not re-deriving correctness (that was 2C-1). The human
reviews the `activatable_diverged` rows before 2C-3.

## The excisable seam (designing for 2D)

The 2D-deletable scaffolding is named and co-located so removal is one cut:

- **One gating function** `_inline_intent(query, det, det_decision, breadth, cfg) -> (merged, gated,
  inline_shadow)` holds the entire dark-wiring surface: the `INLINE_ENABLED` check, classifier call,
  merge, gate, and the `inline_shadow` block. `query_plan_node` calls it, then
  `emitted_decision = gated if ACTIVE_MODE else det_decision`.
- **2D deletion is mechanical:** drop both flag reads, make `_inline_intent` unconditional (rename to
  the permanent classifier step), set `emitted_decision = gated` always, delete
  `diverged`/`activatable_diverged`/`would_be_execution` (degenerate once `gated` *is* the plan).
  What remains is the permanent residue: inline classifier + merge + gate + `latency_ms`/`fallback`
  telemetry + WARN counters.
- **No `would_be` logic leaks** into `_plan_from_routing` or downstream nodes — they only ever see
  the single `emitted_decision`. That containment is what makes the cut clean.

### What survives 2D vs what's scaffolding

| Piece | After 2D |
| --- | --- |
| inline `classify_intent_llm` + `merge_intent` + `trust_gate` | permanent — *the* routing path |
| deterministic `infer_signals` | permanent but demoted — authoritative `entity_scope` + safe-default/fallback target |
| `classifier_latency_ms`, `classifier_error`, `fallback_used` | permanent telemetry |
| error/latency WARN counters | permanent |
| `INTENT_CLASSIFIER_INLINE_ENABLED` | deleted (classifier always runs) |
| `INTENT_CLASSIFIER_ACTIVE_MODE` | deleted (or collapses to a plain kill switch) |
| `would_be` / `diverged` / `activatable_diverged` | deleted (degenerate) |
| `scripts/report_inline_shadow.py` | archived |

## Testing

1. **Byte-for-byte preservation (core guarantee).** Parametrized over a query fixture: emitted
   `query_plan` dict is identical between `(INLINE=off, ACTIVE=off)` and `(INLINE=on, ACTIVE=off)`,
   with the classifier stubbed to return a **divergent high-confidence** route. Proves even a
   would-flip case does not change the plan while inert.
2. **Active-mode wiring.** Same divergent stub, `(INLINE=on, ACTIVE=on)`: emitted plan equals the
   gated route. Guards against a dead branch 2C-3 would discover too late.
3. **Failure → deterministic fallback.** Stub `classify_intent_llm` to raise / time out: no
   exception escapes, `fallback_used=True`, `fallback_reason` set, plan equals the deterministic
   route in both active states.
4. **Trace fields.** Assert `inline_shadow.ran/diverged/activatable_diverged/classifier_latency_ms`
   for diverged-high (activatable), diverged-low (not activatable), and converged cases.
5. **Kill switch.** `(INLINE=off)`: `classify_intent_llm` is **not called** (mock asserts zero
   calls), `inline_shadow.ran=false`.
6. **Offline report unit.** Synthetic `query_run_stats` rows → aggregator; assert error rate, p95
   latency, activatable-divergence rate compute correctly (same pattern as 2C-1's `aggregate` test).

All real LLM stubbed; zero network in the suite. The script's live run against actual
`query_run_stats` is a manual final task in the implementation plan, like 2C-1's scorer run.

## Out of scope (deferred)

- **The flip itself** — flipping `ACTIVE_MODE` to drive routing is 2C-3, gated on this stage's
  shadow report + the 2C-1 correctness gates.
- **Discovery retirement** — 2D.
- **Per-dimension confidence, continuous score** — deferred per roadmap.
- **`requested_format`** — stays `null` until a later stage.
