# Query-Intent Routing — Staged Roadmap (Design 2)

**Date:** 2026-06-12
**Status:** Active roadmap (supersedes the parked stub).
**Source plan:** `prompt_reliability_implementation_plan.md` → "Requires Query-Intent Design" lane.
**Depends on:** `retrieval_control_model_design.md` (Design 1) — **shipped** (control model in
`backend/app/rag/query/control/`, golden-set zero-delta verified 2026-06-12).

Design 2 migrates routing from explicit knobs toward *inferred* intent. The parked stub bundled
five things into one "classifier launch"; this roadmap splits them along the real dependency
shape — **infrastructure → input source → trust decision** — so each stage is independently
shippable and the one behavior-changing step is isolated behind its own gate.

> **Governing invariant (shared with Design 1):** Classify intent once. Apply user policy once.
> Derive execution once. Trace all three separately.

---

## Why staged (not one spec)

- **Graded confidence + shadow routing are infrastructure** — they record "what the new router
  would do" without driving anything.
- **The LLM classifier is an input source** — it answers "does escalation improve classification
  enough to matter?", not "can it drive routing?".
- **Activation is a separate trust decision** — gated on measured evidence.

Bundling these makes Design 2 feel like a single launch when it is really a staged migration.
Each stage gets its own spec → plan → implement cycle, exactly like the Design 1/2 split.

---

## Stage 2A — Deterministic intent + shadow routing (infrastructure)

**Spec:** `query_intent_2a_design.md`. **Deterministic only, zero active behavior change.**

Owns: the `QueryIntent` shape (evolve the shipped `InferredSignals`), the **deterministic
confidence ladder v1** (real code, not yet trusted), the **trust-gate** pure function (born here,
exercised in shadow only), and the `shadow_routing` trace plumbing. Computes "what the new router
would have done" and records it next to the active Design 1 decision.

Confidence ladder v1:
```
high   = explicit broad scope  OR  (grounded entity AND routing marker)
medium = grounded entity only  OR  routing marker only
low    = neither grounded entity nor routing marker
```

**No new graph node in 2A; intent routing is planner-local shadow instrumentation** at the
existing `query_plan_node → _resolve_routing` seam. A separate `intent_classify` node would be
ceremony without payoff given where Design 1 landed. Reconsider a node *only* if intent
classification later needs to be independently retryable, cacheable, streamed, or shared by
multiple downstream graph branches — none of which is a 2A/2B requirement.

Three-part invariant: (1) emitted `query_plan` is byte-for-byte Design 1; (2) shadow divergence is
*expected* zero only because safe-default ≡ the current Design 1 route and 2A intent is
deterministic — **measured, not assumed**; (3) nonzero divergence is recorded, not acted on.

---

## Stage 2B — Hybrid LLM classifier (input source)

**Spec:** `query_intent_2b_design.md`. **Offline-replay shadow; zero live-path change.**

Builds the **real, reusable** temp-0 LLM classifier (strict JSON, timeout/error fallback to the
deterministic intent, `source`/`fallback_used` tagging) and the merge that combines LLM markers with
the deterministic, authoritative `entity_scope`. The LLM owns only the fuzzy marker dimensions
(`needs_synthesis`, `needs_discovery`); `needs_multi_hop` is re-derived; `entity_scope` stays
deterministic.

**Execution = offline replay**, not inline: the live request path stays pure-2A deterministic
(zero added latency/cost). A batch script replays the `{medium, low}` confidence bucket (plus a
`high` control sample) from logged `query_run_stats` and emits disagreement/divergence metrics.

This stage answers **"does LLM escalation improve intent classification enough to matter?"** — it
**measures impact, it does not judge correctness** (that needs 2C's labels) and it does not answer
"can it drive production routing yet?". The **activatable-divergence rate** (high-confidence LLM
routes that differ from Design 1) is the headline go/no-go number into 2C. The classifier built
here is production-ready; 2C wires it inline behind the trust gate.

---

## Stage 2C — sub-staged (evidence → dark wiring → the flip)

2C as one blob has the same failure mode 2A/2B avoided: too much evidence, wiring, and behavior
change in one "trust me" step. Each sub-stage answers exactly one question, in dependency order
(correctness *before* inline, inline shadow *before* the flip):

### 2C-1 — Golden Correctness (evidence) — `query_intent_2c1_design.md`
A labeled **routing golden set** (`data/routing_golden_set_v1.jsonl`, ~40 sharp cases avoiding
trigger words) + an **offline scorer** that grades the **post-gate** route
(`deterministic → llm → merge → derive_routing_decision → trust_gate`) against expected intent —
so "ambiguous → low confidence → safe-default" is first-class. Reports `clear_expected_route_accuracy`,
`clear_missed_activation_rate` (conservative) vs `clear_wrong_route_rate` (dangerous),
`ambiguous_confident_wrong_count`, `llm_vs_deterministic_delta`, per-marker P/R. **No behavior
change, no inline LLM.** Answers *"is the classifier/merge correct enough against labels?"*

v1 gates: `clear_expected_route_accuracy ≥ 90%`; `ambiguous_confident_wrong_count == 0`;
`clear_wrong_route_count == 0` (allow missed activations, never wrong routes); `llm_vs_deterministic_delta ≥ 0`;
clear-control route regressions `== 0` or reviewed.

### 2C-2 — Inline Shadow (dark wiring)
Move the classifier from offline replay to **inline**, behind two orthogonal flags:
`INTENT_CLASSIFIER_INLINE_ENABLED` (does it run live) and `INTENT_CLASSIFIER_ACTIVE_MODE` (may the
gated result drive `query_plan`). Default: inline off / shadow, active false. This is where the
latency budget, timeout→deterministic-fallback, and the kill switch live. **Ships dark; no behavior
change.** Answers *"can it run inline safely under real latency/failure while still inert?"*

### 2C-3 — Trust-Gated Activation (the flip)
Flip `INTENT_CLASSIFIER_ACTIVE_MODE` so high-confidence inferred routes drive `query_plan`, gated on
the 2C-1 correctness gates + 2C-2 production shadow passing. The first behavior change, with instant
rollback via the flag. Answers *"should we let high-confidence routes actually drive?"*

### 2D — Discovery retirement (follow-on)
**Kept out of 2C-3** — the router flip is already the first behavior change; deleting a legacy
breadth value at the same time muddies the blame trail. Retire `discovery` only after activation
proves boring.

---

## Cross-cutting decisions (parked, settled during brainstorming)

- **`QueryIntent` = evolve `InferredSignals` in place** — add `source` + `fallback_used`, grade
  `confidence`. No parallel type; existing control/planner consumers unchanged. Optional rename to
  `QueryIntent` deferred to 2C.
- **Confidence is one *overall* level** in v1; per-dimension confidence deferred.
- **Hybrid combination = deterministic-first, LLM escalation** below `high`; LLM wins on
  disagreement (it ran *because* deterministic was unsure); any LLM failure → deterministic
  fallback. (2B.)
- **3-level ladder, calibrated in shadow (2C)** — no continuous score / magic floats unless the
  ladder proves too coarse.
- **Trust gate:** trust the inferred route only if `confidence == high`; else safe-default ≡ the
  current Design 1 route. Born in 2A (shadow), activated in 2C.
- **Two orthogonal flags (2C-2):** `INTENT_CLASSIFIER_INLINE_ENABLED` (runs live) and
  `INTENT_CLASSIFIER_ACTIVE_MODE` (may drive `query_plan`); default inline-off/shadow, active false —
  clean dark-launch + rollback. Manual staging possible by reading the trace before flipping.
- **`requested_format`** stays `null` until a later stage adds the explicit-format signal.

---

## Status / order

1. 2A — **shipped** (deterministic intent + shadow routing; zero-delta verified).
2. 2B — **shipped** (offline-replay LLM classifier; closeout smoke clean).
3. 2C-1 — Golden Correctness: spec → plan → implement (**next**).
4. 2C-2 — Inline Shadow (dark wiring).
5. 2C-3 — Trust-Gated Activation (the flip).
6. 2D — Discovery retirement (follow-on).
4. Discovery retirement (within 2C or immediately after).
