# Design 2A — Deterministic Intent + Shadow Routing

**Date:** 2026-06-12
**Status:** Proposed
**Roadmap:** `query_intent_routing_roadmap.md` (Design 2, Stage A of A/B/C).
**Depends on:** `retrieval_control_model_design.md` (Design 1) — shipped.

Stage 2A makes intent classification explicit and confidence-graded, and stands up the
shadow-routing harness — **deterministic only, no LLM, no active behavior change.** It is the
substrate 2B (LLM escalation) and 2C (golden set + metrics + trust-gated activation) build on.

> **Governing invariant (shared):** Classify intent once. Apply user policy once. Derive
> execution once. Trace all three separately.

---

## 1. Scope & the three-part invariant

2A adds: graded confidence on the inferred tier, a `source`/`fallback_used` provenance pair, a
pure **trust-gate** function, and a `shadow_routing` record of "what the new router would have
done." None of it drives behavior.

**Invariant:**
1. **No active behavior change** — the emitted `query_plan` is byte-for-byte Design 1. Hard
   guarantee, asserted in tests and the golden set.
2. **Shadow divergence is *expected* zero, not *assumed* zero.** It is zero only because
   safe-default ≡ the current Design 1 route (§4) and 2A's intent is deterministic = Design 1's.
   We **measure** divergence; we do not hard-code the expectation.
3. **Nonzero divergence → recorded, never acted on.** Catches adapter bugs or any future
   redefinition of safe-default.

This mirrors Design 1's discipline: land the substrate, instrument the delta, change behavior only
later (2C) when evidence says it is safe.

---

## 2. `QueryIntent` — evolve `InferredSignals` in place

Design 1 shipped `InferredSignals`
([inferred.py](../../backend/app/rag/query/control/inferred.py)) with `entity_scope`, `needs_synthesis`,
`needs_discovery`, `needs_multi_hop`, `requested_format`, `confidence`, `reasons`. 2A evolves it —
**no parallel type, no adapter** (existing control/planner consumers already line up):

| Field | Change in 2A |
|---|---|
| `confidence` | was constant `"high"` → **graded** `"high" \| "medium" \| "low"` (§3) |
| `source` | **new**, `"deterministic"` throughout 2A (2B adds `"llm_escalated"`) |
| `fallback_used` | **new**, `False` throughout 2A (2B sets `True` on LLM failure) |
| all others | unchanged |

Confidence derives from fields the object already holds (`entity_scope`, `needs_synthesis`,
`needs_discovery`) — `infer_signals` needs no new inputs in 2A (`matched_entities` stays reserved
for the 2B classifier). Optional rename `InferredSignals` → `QueryIntent` is deferred to 2C to keep
2A's blast radius minimal.

---

## 3. Deterministic confidence ladder v1

```
high   = explicit broad scope  OR  (grounded entity AND routing marker)
medium = grounded entity only  OR  routing marker only
low    = neither grounded entity nor routing marker
```

Definitions (resilient as `QueryIntent` grows):
- **grounded entity** = `entity_scope ∈ {single, multi}` (entity linking succeeded).
- **explicit broad scope** = `entity_scope == "broad"` (matched a `所有公司`-type broad signal —
  an explicit, strong breadth marker).
- **routing marker** = any deterministic intent signal: today `needs_synthesis` **or**
  `needs_discovery`; extensible to relationship / cross-document / explicit-format / multi-hop as
  those signals are added.

Worked cases:

| Query shape | scope | marker | confidence |
|---|---|---|---|
| `所有公司提到X` | broad | — | **high** (explicit broad) |
| grounded entity + `比较/区别` | single/multi | yes | **high** (corroborated) |
| plain single-entity lookup | single | no | **medium** (grounded only) |
| two entities, no compare marker | multi | no | **medium** (could be accidental) |
| `比较X和Y`, X/Y not linked | none | yes | **medium** (ungrounded marker — "lone keyword never high") |
| bare/implicit question | none | no | **low** (flying blind — 2B's escalation target) |

The ladder is **one overall level** (per-dimension deferred), deliberately legible v1, and
**calibrated in 2C** against the routing golden set — no continuous score, no magic floats.

It is computed inside `infer_signals` (so the level travels with the intent) via a small pure
helper, e.g. `_confidence(entity_scope, has_routing_marker) -> Literal["high","medium","low"]`.

---

## 4. Trust gate (pure function, shadow-only in 2A)

```python
def trust_gate(intent, inferred_decision, design1_decision):
    return inferred_decision if intent.confidence == "high" else design1_decision
```

**safe-default ≡ the decision Design 1's planner currently emits** (the active route), **not** a
re-derived conservative baseline. This is the compat anchor that makes 2A inert: when the gate
fires (confidence ≠ high) it returns the Design 1 route, which — in 2A — is also what the inferred
route produced, because both derive from the same deterministic intent. So the gate never changes
the shadow outcome in 2A, at any confidence level.

The function is **born in 2A** and exercised in shadow only; **2C activates it** (flips which
decision drives `query_plan`). In 2B, divergence first appears when LLM-enriched intent yields a
`high`-confidence route that differs from Design 1.

---

## 5. Shadow instrumentation — planner-local, no new graph node

Design 1 folded intent into the planner, so 2A enriches that seam in place. **No
`intent_classify` graph node** (see roadmap for the future-node trigger conditions).

At `query_plan_node → _resolve_routing` ([planner.py](../../backend/app/rag/query/planner.py)):
1. derive `QueryIntent` (with graded `confidence`, `source="deterministic"`, `fallback_used=False`),
2. compute the **active** Design 1 decision exactly as today — this drives `query_plan`,
3. compute `would_be = trust_gate(intent, inferred_decision, design1_decision)`. **2A does not
   compute a second decision** just to fill the future-shaped signature: `inferred_decision` and
   `design1_decision` are the *same* value/object from the existing deterministic `_resolve_routing`
   path, so 2A may pass that one decision as both arguments. **2B is where they become distinct**
   (LLM-inferred vs Design 1).
4. record both into the existing `routing_trace`, persisted via `query_observability` →
   `resolved_settings` → `settings_json` (**no schema change** — Design 1 already plumbs
   `routing_trace` through `_OBSERVABILITY_STATE_KEYS`).

Trace shape (enriched sections; `intent`/`policy`/`infra`/`routing_decision` from Design 1 remain):
```json
{
  "intent": { "confidence": "medium", "source": "deterministic", "fallback_used": false },
  "shadow_routing": {
    "would_be_decision": { "...": "RoutingDecision fields" },
    "trust_gated": true,
    "diverged": false
  }
}
```
`diverged` = the two decisions differ, computed (not assumed) by **normalized execution-field
comparison**. The trace may serialize the full `RoutingDecision`, including explanatory `reasons`
and `vetoes`, but divergence compares only behavior-bearing fields (HyDE, expansion, multi-hop,
fallback, budget profile, prompt variant, answer shape, and steps). Dataclass `__eq__` would happen
to work in 2A, but 2B may construct the would-be decision through a different path (LLM-fed), so
trace metadata must not create false divergence. `trust_gated` = whether the gate fired (confidence
≠ high).

---

## 6. Components & boundaries

| Unit | Responsibility | Notes |
|---|---|---|
| `infer_signals` (evolve) | emit `QueryIntent` incl. graded `confidence`, `source`, `fallback_used` | `control/inferred.py`; pure |
| `_confidence` (new helper) | ladder v1 → `high/medium/low` | `control/inferred.py`; pure, table-tested |
| `trust_gate` (new) | `(intent, inferred, design1) → decision` | `control/routing.py`; pure |
| `build_routing_trace` (extend) | add `intent` provenance + `shadow_routing` section | `control/routing.py` |
| `query_plan_node` (extend) | wire shadow computation at the `_resolve_routing` seam; emitted `query_plan` unchanged | `planner.py` |
| `query_observability` | already persists `routing_trace`; assert the new keys survive | no change expected |

---

## 7. Tests / acceptance

- **Active unchanged (the guarantee):**
  - Unit: emitted `query_plan` identical across representative queries (reuse the Design-1
    characterization net as the anchor).
  - Golden set: retrieval-only Hit@5/Hit@10 and full pass rate identical to the current accepted
    Design 1 baseline (same gate Design 1 passed).
- **Ladder v1:** unit tests for every row in the §3 table (broad, grounded+marker, plain lookup,
  multi-no-marker, ungrounded marker, bare query).
- **Trust gate:** unit tests — `high` → inferred decision; non-`high` → Design 1 decision; pure /
  no side effects.
- **Shadow inert + honest:** unit asserts `shadow_routing.diverged == false` across the
  deterministic corpus; a *forced* mismatch (inject a divergent decision) asserts it is **recorded**
  (`diverged=true`) and **not acted on** (emitted `query_plan` still Design 1).
- **Trace persists:** `routing_trace.intent` + `routing_trace.shadow_routing` reach
  `resolved_settings` / `settings_json`.

---

## 8. Non-goals (2A)

- No LLM, no escalation, no `requested_format` extraction (2B / later).
- No active routing change — the trust gate is shadow-only.
- No routing golden set, no shadow metrics, no promotion gates, no kill switch (2C).
- No discovery retirement (2C or follow-on).
- No new graph node; no per-dimension confidence; no continuous confidence score.
- No rename of `InferredSignals`/`retrieval_flavor` (deferred).
