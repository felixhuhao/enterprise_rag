# Design 2C-1 — Routing Golden Set + Correctness Scoring

**Date:** 2026-06-12
**Status:** Proposed
**Roadmap:** `query_intent_routing_roadmap.md` (Design 2, Stage 2C-1 of 2C-1/2C-2/2C-3 + 2D).
**Depends on:** `query_intent_2b_design.md` (2B — LLM classifier + merge) — shipped.

2C-1 is the **evidence** stage of 2C. It builds a labeled **routing golden set** and an **offline
correctness scorer** that grades the *post-gate* route produced by the LLM-enriched intent against
expected routing intent. **No behavior change, no inline LLM** — it reuses 2B's classifier/merge
offline and produces the correctness numbers the 2C-3 activation gate must clear.

It answers one question: **is the classifier/merge correct enough, against labels, to be worth
activating?** It does not run inline (2C-2) or drive routing (2C-3).

> **Governing invariant (shared):** Classify intent once. Apply user policy once. Derive execution
> once. Trace all three separately.

---

## 1. Scope

- A new labeled corpus `data/routing_golden_set_v1.jsonl` of paraphrase cases that **avoid current
  trigger words**, plus clear-control keyword cases.
- An offline scorer `backend/scripts/score_routing_golden_set.py` that, per case, runs the full
  intent pipeline (deterministic → LLM → merge → decision → trust gate) and grades the **post-gate
  route** against the label.
- A summary of the §5 metrics + the §6 promotion gates.

**Boundary:** the scorer's oracle is `derive_routing_decision(expected_intent)` — it tests whether
**LLM-enriched intent feeds the (already-characterized) decision table correctly**, *not* the
decision table itself (Design 1 / 2A already characterized that). This is the correct abstraction
boundary: 2C-1 judges intent inference + trust-gate safety, not implementation details like
`prompt_variant`, `steps`, or fallback wording.

**Live invariant:** 2C-1 adds no request-path code; the golden set + main eval still match the
accepted Design 1 baseline.

---

## 2. The routing golden set

`data/routing_golden_set_v1.jsonl`, separate from `challenge_golden_set_v1.jsonl` (keeps
routing-regression evidence distinct from answer-quality). **~40 sharp cases > 100 mushy ones.**
Drafted by the implementer (the hard part is writing natural queries that avoid existing trigger
words while still exercising the intended weakness); **labels/coverage reviewed by the user.**

Category mix (v1):

| Category | Count | Exercises |
|---|---|---|
| implicit comparison / synthesis | 6-8 | synthesis intent with no `比较/区别/异同/对比` keyword |
| mixed zh/en / paraphrase | 6-8 | marker phrased in English or paraphrase |
| discovery over an unspecified/implied set, no broad keyword | 6-8 | questions that *feel* broad but resolve to `entity_scope=none, needs_discovery=true` — tests **marker** detection, not `entity_scope` inference |
| discovery without keywords | 6-8 | discovery intent with no `哪些公司/竞争对手/...` keyword (`needs_discovery=true`) |
| alt-phrasing multi-hop / responsibility | 6-8 | responsibility/multi-hop with no `谁负责/...` keyword |
| clear-control (keyword) | 5-8 | cases keywords already route correctly — regression guard |

**Scope note — every fuzzy case must be *marker-fixable*.** 2B's LLM infers only `needs_synthesis` /
`needs_discovery`; it **never** infers `entity_scope` (deterministic entity-linking owns that, §3).
So a pure "broad-scope without keywords" case — one that would require `entity_scope: none → broad`
inference — is **out of scope** for 2B/2C-1 and is reframed above as a discovery-marker case
(`entity_scope=none, needs_discovery=true`). `entity_scope=broad` inference is a future capability
beyond this stage.

Each fuzzy category's 6-8 allocation **includes 2-3 explicitly-`ambiguous` cases** (genuinely
underspecified — they exercise the safety gate, not accuracy); they are counted *inside* the
category totals, not added on top, so the corpus stays ~40. The scorer reports ambiguous metrics
separately (§5) regardless of category.

---

## 3. Case schema

```json
{
  "id": "implicit_discovery_001",
  "query": "API迁移指南归谁写？",
  "entity_mode": "none",
  "matched_entities": [],
  "retrieval_breadth": "balanced",
  "strict_evidence": false,
  "case_class": "clear",
  "expected_intent": {
    "entity_scope": "none",
    "needs_synthesis": false,
    "needs_discovery": true
  },
  "must_activate": true
}
```

Ambiguous case:
```json
{
  "id": "ambiguous_discovery_001",
  "query": "...",
  "case_class": "ambiguous",
  "expected_intent": { "needs_synthesis": false, "needs_discovery": true },
  "acceptable": "expected_route_or_safe_default"
}
```

Field rules:
- **`entity_mode`** drives deterministic `entity_scope` (`infer_signals` derives scope from
  `entity_mode`); **`matched_entities`** is fixture context / reserved for the classifier, not a
  scope input today.
- **`expected_intent.entity_scope`** is a **consistency check, not an authority**: the scorer asserts
  `infer_signals(query, entity_mode, matched_entities).entity_scope == expected_intent.entity_scope`
  and **errors the fixture** on mismatch (catches bad cases rather than hand-waving grounding).
- **`retrieval_breadth`** (not legacy `retrieval_flavor`), unless a case deliberately exercises
  legacy compat (then it sets `retrieval_flavor` explicitly).
- **`must_activate`** (bool, optional; default false) describes the *expectation* that a `clear`
  case should activate to the expected route — **not** a mirror of model output, and it **does not
  redefine route accuracy.** Route accuracy is purely `actual_route == expected_route` (§4). A
  `must_activate` case where the gate safe-defaults is tracked **separately** as a *missed
  activation* (§5) — it does not by itself subtract from `clear_expected_route_accuracy` (the route
  may still be correct). (No `confidence_floor` field — `must_activate` is the single expectation
  flag; per-confidence-band assertions are out of scope for v1.)
- **`needs_multi_hop`** is never labeled — it is re-derived from `(entity_scope, needs_discovery)`,
  same rule as the pipeline.

---

## 4. The scorer — per case

Builds a replay `QueryConfig` from the case: `retrieval_breadth` / `strict_evidence` as given;
infra flags (`use_hyde/use_query_expansion/use_multi_hop`) default **ON** so the test isolates
intent→route (vetoes don't mask the signal; a case may override to test veto interaction); numeric
budget params from the current stable defaults.

```
det      = infer_signals(query, entity_mode, matched_entities)        # deterministic intent
llm      = classify_intent_llm(query, det)                            # 2B classifier (offline)
merged   = merge_intent(det, llm)
expected = InferredSignals(entity_scope=…, needs_synthesis=…,
                           needs_discovery=…, needs_multi_hop=rederive(…))

# budget_reason IS an execution field, and resolve_budget_profile depends on needs_synthesis —
# so resolve the budget PER INTENT, not once. Otherwise an implicit-synthesis case
# (det.needs_synthesis=False vs merged/expected=True) would be graded against the wrong route.
def route(intent):
    b = resolve_budget_profile(breadth, intent.entity_scope, intent.needs_synthesis, cfg)
    return derive_routing_decision(intent, breadth, cfg, budget_reason=b.reason)

design1_decision = route(det)        # safe-default (deterministic route)
merged_decision  = route(merged)
expected_route   = route(expected)
actual_route     = trust_gate(merged, merged_decision, design1_decision)   # POST-GATE
```

Comparison uses the **execution-field subset** (2B's public `decision_execution_dict`, which also
accepts a logged decision dict). **Route accuracy and activation are orthogonal axes** — accuracy is
`actual_route == expected_route`; activation is `merged.confidence == high`. Outcome per case:

**Clear cases** (two independent measures):
- **Accuracy:** `pass` iff `actual_route == expected_route` (by activation *or* a safe-default that
  happens to match) → feeds `clear_expected_route_accuracy`.
- **Activation (separate):** a `must_activate` case with `merged.confidence != high` (gate
  safe-defaulted) is a **missed_activation** — tracked separately, **does not** subtract from
  accuracy. A case with `merged.confidence == high and actual_route != expected_route` is a
  **wrong_route** (the dangerous failure; it is also an accuracy miss).

**Ambiguous cases** — safe-pass must check the **gate**, not just route equality (a high-confidence
route that coincides with `design1_decision` but ≠ expected is still a confident wrong route):
- **safe_pass** iff `actual_route == expected_route` **OR**
  `(merged.confidence != "high" AND actual_route == design1_decision)`.
- **confident_wrong** iff `merged.confidence == "high" AND actual_route != expected_route` (the hard
  safety failure).

**Deterministic baseline:** the deterministic-only route is `design1_decision` (the gate is inert
when both args are the deterministic decision), scored for accuracy against `expected_route` the same
way — this is the keyword baseline the LLM must beat-or-match.

---

## 5. Metrics

| Metric | Definition |
|---|---|
| `clear_expected_route_accuracy` | clear cases where `actual_route == expected_route` (route axis, pure) |
| `clear_missed_activation_rate` | `must_activate` clear cases where the gate safe-defaulted (`confidence != high`) — **activation axis, independent of route correctness** (conservative) |
| `clear_wrong_route_rate` / `_count` | clear cases with `confidence == high` and `actual_route != expected_route` (dangerous) |
| `ambiguous_safe_default_rate` | ambiguous cases the gate safe-defaulted (`confidence != high and actual == design1`) |
| `ambiguous_confident_wrong_count` | ambiguous cases with `confidence == high and actual != expected` |
| `llm_vs_deterministic_delta` | `clear_expected_route_accuracy` − deterministic clear accuracy |
| per-marker precision/recall | `needs_synthesis`, `needs_discovery` (merged vs `expected_intent`) |
| parse/fallback rate | classifier error/timeout/parse-fail → deterministic |

All numbers reported overall and per category. `missed_activation` (conservative) is reported
*separately* from `wrong_route` (dangerous) — they are not equally bad.

---

## 6. Promotion gates (v1)

The bar 2C-3 must clear (defined here, evaluated here against the golden set; re-evaluated in 2C-3
against production shadow):

1. `clear_expected_route_accuracy >= 90%`.
2. `ambiguous_confident_wrong_count == 0` (hard safety cap — with ~40 cases, one is already a real
   smell; fail closed and inspect).
3. `clear_wrong_route_count == 0` (allow missed activations; **never** confidently wrong routes).
4. `llm_vs_deterministic_delta >= 0` (no regression on what keywords already get right).
5. Clear-control execution-route regressions `== 0`, or each separately reviewed.
6. Parse/fallback rate **reported**; no hard gate in 2C-1 unless failures are high.

---

## 7. Components & boundaries

| Unit | Responsibility | Where |
|---|---|---|
| `routing_golden_set_v1.jsonl` | labeled paraphrase + control corpus | `data/` (root, alongside `challenge_golden_set_v1.jsonl`) |
| `score_routing_golden_set.py` | per-case pipeline + post-gate scoring → metrics/gates | `backend/scripts/` |
| reused | `infer_signals`, `classify_intent_llm`, `merge_intent`, `derive_routing_decision`, `trust_gate`, `decision_execution_dict` | shipped 2A/2B |

**`.gitignore`:** root ignores `data/*` except allowlisted files, so the corpus needs an explicit
`!data/routing_golden_set_v1.jsonl` entry (next to `!data/challenge_golden_set_v1.jsonl`) to be
tracked.

The scorer reuses shipped units only — it adds **no** production code. The fixture-consistency check
(`entity_scope`) and the post-gate outcome classification are the only new logic, both in the script
and unit-testable with a tiny inline fixture.

---

## 8. Acceptance

- **Corpus authored + user-reviewed:** ~40 cases across the §2 mix, labels confirmed.
- **Scorer runs offline** and emits per-case `.jsonl` + `_summary.json` with the §5 metrics and a
  pass/fail line per §6 gate.
- **Fixture integrity:** the `entity_scope` consistency check passes for every case (no hand-waved
  grounding).
- **Live path unchanged:** no request-path code added.
- The summary + gate verdicts are the evidence carried into the 2C-2 (wire inline) / 2C-3 (activate)
  go/no-go.

---

## 9. Non-goals

- No inline classifier, no latency/timeout wiring (2C-2), no activation flags (2C-2/2C-3).
- No trust-gate activation / behavior change (2C-3).
- No discovery retirement (2D).
- No `requested_format`, no new graph node, no `InferredSignals`→`QueryIntent` rename.
- No re-characterizing the decision table (Design 1/2A own that); the oracle *uses* it.
