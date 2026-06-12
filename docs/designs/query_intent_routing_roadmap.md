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

**Still shadow-only, zero active behavior change.**

Adds the temp-0 LLM escalation that runs **only where deterministic confidence is below `high`**:
strict JSON schema, timeout/error fallback to the deterministic intent (`fallback_used=true`,
`source` tagging), and disagreement logging (deterministic vs LLM intent, and shadow vs active
routing — `diverged` can now become true).

This stage answers **"does LLM escalation improve intent classification enough to matter?"** It
explicitly does **not** answer "can it drive production routing yet?" — that is 2C.

---

## Stage 2C — Golden set, metrics, trust-gated activation (the behavior change)

**The one stage that changes behavior, and only when the gates pass.**

Owns: the **routing golden set** (paraphrase cases that intentionally avoid current trigger
words — implicit comparisons, mixed zh/en, broad-entity questions without `所有/哪些/各`,
discovery without current keywords, alternative-phrasing multi-hop), **shadow metrics**,
**promotion gates**, the **active-mode flag**, a **rollback/kill switch**, and the first
behavior-changing rollout. Trust-gated activation lives here because the evidence machinery exists
by then.

Promotion gates (all required):
1. Retrieval-only Hit@5 / Hit@10 do not regress on the current golden set.
2. Full-mode pass rate within accepted baseline tolerance.
3. ≥90% expected-route accuracy on high-confidence routing cases.
4. Ambiguous cases: hit the expected route **or** return low confidence and safe-default — never a
   confident wrong route.
5. Every mismatch recorded with a reason and reviewed before rollout.

**Discovery retirement is NOT in 2A/2B.** It rides 2C (after the router is trusted) or a follow-on
migration immediately after 2C, so the earlier stages stay genuinely zero-delta.

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
- **Single global shadow→active flag** (not per-dimension); manual staging possible by reading the
  trace before flipping.
- **`requested_format`** stays `null` until a later stage adds the explicit-format signal.

---

## Recommended order

1. 2A spec → plan → implement (this is next).
2. 2B spec → plan → implement.
3. 2C spec → plan → implement.
4. Discovery retirement (within 2C or immediately after).
