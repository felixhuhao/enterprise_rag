# Query-Intent Routing — Design Stub (parked)

**Date:** 2026-06-12
**Status:** PARKED. Depends on **Design 1 — Retrieval Control Model**.
**Source plan:** `docs/prompt_reliability_implementation_plan.md` → "Requires Query-Intent Design" lane.

This stub parks the design decisions reached while brainstorming the prompt-reliability
"design lane". During that session we concluded the lane is really **two** designs:

1. **Retrieval Control Model** (foundational substrate — its own spec, designed first).
2. **Query-Intent Routing** (this document — a *consumer* of the control model).

Do not implement from this stub. It exists so the second design cycle starts warm.
Revisit and promote it to a full spec only after Design 1 is settled.

---

## Governing invariant (shared with Design 1)

> Classify intent once. Apply user policy once. Derive execution once. Trace all three separately.

Testable consequence: three ordered, side-effect-free stages, each writing its own trace
section, none reaching back to mutate another's output.

---

## Layered structure (build/merge order = topological order)

```
1. QueryIntent object   (the contract everything reads/writes)
2. Hybrid classifier    (produces QueryIntent: deterministic ⊕ optional LLM)
3. Decision table       (QueryIntent × retrieval_breadth × config → RoutingDecision)
4. Routing golden set   (paraphrase cases labelled with expected routes)
5. Shadow-mode metrics  (gates comparing new vs current, using 4)
```

Layers 1–3 are runtime; 4–5 are the validation harness that gates flipping layer 3 from
shadow to active. Nothing in 1–3 changes behaviour until layer 5's gates pass.

---

## 1. `QueryIntent` object

The single inferred-intent contract. Frozen dataclass. **Inferred tier only** — not user
policy, not derived execution.

| Field | Type | Notes |
|---|---|---|
| `entity_scope` | `single \| multi \| broad \| none` | refines entity_confirm's raw mode; **classification only**, never an execution label |
| `needs_synthesis` | `bool` | replaces `SYNTHESIS_QUERY_MARKERS` |
| `needs_discovery` | `bool` | replaces `DISCOVERY_KEYWORDS` |
| `needs_multi_hop` | `bool` | replaces multi-hop keyword gate |
| `requested_format` | `none \| bullets \| table` | explicit user presentation request ("列出", "table") — deterministic, high-precision extraction; the **only** answer-shape input that lives in intent |
| `confidence` | `low \| medium \| high` | 3-level ladder, overall trust |
| `reasons` | `list[str]` | reason codes, e.g. `synthesis:llm`, `broad:keyword+grounding` |
| `fallback_used` | `bool` | LLM failed/timed out → deterministic |
| `source` | `deterministic \| llm_escalated` | provenance for shadow analysis |

**Cut from earlier drafts (YAGNI):**
- `comparison_type` subtype (entity_vs_entity/temporal/attribute) — nothing branches on it
  today; it is only ever a bool. Re-add when a prompt variant actually consumes the subtype.
- `answer_shape` as a *classified* field — it is **derived** in the routing decision
  (`requested_format or derive(needs_synthesis)`), not invented by the classifier.

---

## 2. Hybrid classifier

Two stages behind one flag.

**Deterministic stage (always runs).** Folds the three existing keyword sites
(`_BROAD_SIGNALS`, `SYNTHESIS_QUERY_MARKERS`, `DISCOVERY_KEYWORDS`/`RESPONSIBILITY_HOP_KEYWORDS`)
plus entity grounding into one function → candidate `QueryIntent` + ladder confidence:

- **high** — explicit signal **and** entity grounding, or two independent signals
- **medium** — a single signal
- **low** — none, or conflicting signals
- Hard rule: **a lone keyword never reaches `high`** (capped at medium). Keywords can only
  *confirm* a route grounding/LLM also supports, never unilaterally decide one.

**LLM stage (escalation).** Runs **only when deterministic confidence < high**. Temp 0,
bounded tokens, strict JSON = the `QueryIntent` fields. On any error/timeout/parse-fail →
keep deterministic intent, `fallback_used=true`, `source=deterministic`. When it runs and
parses, `source=llm_escalated` and it may reach high. **When the LLM runs and disagrees with
the deterministic candidate, the LLM wins** (it was escalated *because* deterministic was not
confident).

**Two boolean gates:**
- escalate to LLM **unless** deterministic confidence is `high`
- trust the inferred route **only if** final confidence is `high`, else safe-default (layer 3)

Default posture: **escalate aggressively, trust conservatively.** Relax the escalation gate
upward only as shadow data shows the LLM is reliable.

**Calibration note:** the 3-level ladder is deliberately coarse and unproven. It is to be
*exercised in shadow mode* and tuned from real disagreement data. A continuous confidence
score is a documented future refinement **only if** the ladder proves too coarse — not built
up front (avoids magic-number calibration with no data).

---

## 3. Decision table

Pure function `(QueryIntent, retrieval_breadth, QueryConfig) → RoutingDecision`. Replaces the
if/else ladder in `backend/app/rag/query/planner.py`.

The **RoutingDecision IS the structured retrieval strategy** (no separate vague enum beside
its own parts):

```
RoutingDecision = {
  use_hyde, use_query_expansion, use_multi_hop,   # derived, then infra-vetoed
  budget_tier,                                     # tight | standard | wide
  prompt_variant,
  answer_shape,                                    # requested_format or derive(needs_synthesis)
  steps,                                           # e.g. ["multi_hop"] — execution path
  reasons,
}
```

Rules:
- **`retrieval_breadth` (user policy) always wins** on breadth. Intent drives nothing about
  breadth; it drives synthesis/scope/multi-hop/answer-shape.
- **Execution features split into two classes** (established by Design 1):
  - *Intent-requested steps* (`multi_hop`, `discovery`) — `intent.requests ∧ breadth.permits ∧
    infra.enables`; breadth is **veto-only** (suppress, never force).
  - *Breadth-owned strategy* (`use_hyde`, `use_query_expansion`, `budget_tier`) — `breadth.sets
    ∧ infra.enables`; **intent never touches these.** No `needs_hyde`/`needs_expansion` fields.
- `strict_evidence` is **config-only** — a separate promise from breadth; intent never relaxes it.
- **Kill-switch / veto semantics** for derived booleans, e.g.
  `use_multi_hop = needs_multi_hop && breadth_permits_multi_hop && enable_multi_hop`.
  Config `enable_*` can only *veto*, never *force*.
- **Trust gate:** if final `confidence != high`, the table ignores inferred dimensions and
  returns the **current safe default** (today's keyword/config result). Low-confidence queries
  behave exactly as today — the safety contract.
- Emits the part-1 `routing_decision` trace object as a byproduct (`reason_codes`, `source`,
  `steps`).

---

## 4. Graph integration & shadow mode

- New node `intent_classify` between `entity_confirm` and `query_plan`. Must sit *after*
  entity_confirm because entity grounding is an input to the confidence ladder.
- **Shadow mode (single global flag, default on-shadow):** `intent_classify` runs, the
  decision table computes the *would-be* `RoutingDecision`, both the would-be and the
  actually-executed plan are written to the trace and into `query_run_stats` (extends the
  existing `query_observability` payload). **Old routing still drives behaviour.**
- **Active mode:** one flag flip; decision table output drives the plan. No per-dimension
  flags now (table is structured to allow them later — YAGNI).

---

## 5. Routing golden set

A **new** file, separate from the existing golden set (keeps prompt-quality regression
separate from routing regression). Built from paraphrases that **intentionally avoid current
trigger words**: implicit comparisons, mixed zh/en, broad-entity questions without
`所有/哪些/各`, discovery without current keywords, multi-hop responsibility questions with
alternative phrasing. Each case carries a **manually-labelled expected route** (expected
`QueryIntent` dimensions).

---

## 6. Shadow metrics & promotion gates

Promotion shadow→active requires **all** of:
1. Retrieval-only Hit@5 / Hit@10 do not regress on the current golden set.
2. Full-mode pass rate within accepted baseline tolerance.
3. ≥90% expected-route accuracy on high-confidence routing cases.
4. On ambiguous cases: classifier either hits the expected route **or** returns low confidence
   and safe-defaults (never a confident wrong route).
5. Every mismatch has a recorded reason, reviewed before rollout.

Measured as expected-route accuracy vs the current keyword baseline — not trace readability.

---

## Dependencies on Design 1 (Retrieval Control Model)

This design assumes Design 1 has already delivered:
- `retrieval_breadth` (precise | balanced | broad), `discovery` flavor removed.
- `enable_*` kill-switches with veto-only semantics.
- Named budget tiers (`tight | standard | wide`).
- `entity_scope` separated from execution label; `routing_decision.steps` for execution path.
- `strict_evidence` kept separate from breadth.

Open question inherited from Design 1: whether `retrieval_breadth` is a **vetoer** of
intent-derived steps (e.g. `precise` suppresses multi-hop) or only a **shaper** of
strategy/budget. The kill-switch formula above assumes vetoer; confirm once Design 1 decides.
