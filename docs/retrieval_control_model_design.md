# Retrieval Control Model — Design

**Date:** 2026-06-12
**Status:** Proposed
**Source plan:** `docs/prompt_reliability_implementation_plan.md` → "Requires Query-Intent Design" lane.
**Downstream consumer:** `docs/query_intent_routing_design_stub.md` (Design 2).

This is **Design 1** of two. It reorganizes today's routing knobs into a four-tier control
model with a single authority chain. It adds **no inference, no LLM, and no `QueryIntent`
object** — those belong to Design 2 (Query-Intent Routing), which is a *consumer* of the
substrate defined here.

The split exists for clean attribution: Design 1 is a behavior-preserving reorganization with
an identical-golden-set acceptance gate; Design 2 layers new (inferred) behavior on a frozen
substrate.

---

## 1. Purpose & governing invariant

Today's routing knobs are a flat namespace where knobs secretly override one another:
`retrieval_flavor` mixes retrieval width with task type; `entity_mode` is both a scope
classification and a post-hoc execution label; `use_hyde`/`use_query_expansion`/`use_multi_hop`
are voted on by config, flavor, *and* keyword gates simultaneously. The result is a planner
nobody can reason about without tracing every branch.

This design separates four concerns — **user preference, inferred query type, derived
execution, and infra capability** — into four tiers, each with one clear owner, connected by a
single one-way authority chain.

> **Governing invariant:** Classify intent once. Apply user policy once. Derive execution once.
> Trace all three separately.

**Testable consequence:** three ordered, side-effect-free stages, each writing its own trace
section, none reaching back to mutate another's output. A change that makes the planner read
intent *and* config in the same breath to decide a route must fail a test.

---

## 2. The four-tier namespace

```
User/admin config (preference):
  retrieval_breadth        # precise | balanced | broad
  strict_evidence          # bool — answer contract, NOT retrieval width

Inferred (deterministic in Design 1; hybrid classifier in Design 2):
  entity_scope             # single | multi | broad | none
  needs_synthesis          # bool
  needs_discovery          # bool
  needs_multi_hop          # bool
  requested_format         # table | bullets | prose | null  (explicit user ask)
  confidence               # (Design 2; in Design 1 always "high"/deterministic)
  reasons                  # list[str]

Derived (RoutingDecision — the strategy object):
  use_hyde
  use_query_expansion
  use_multi_hop
  budget_tier              # tight | standard | wide
  prompt_variant
  answer_shape             # requested_format or derive(needs_synthesis)
  steps                    # execution path, e.g. ["multi_hop"]
  reasons
  vetoes

Infra caps (config, NEVER routing — veto-only):
  enable_rerank
  enable_table_expand
  enable_context_expand
  enable_hyde
  enable_query_expansion
  enable_multi_hop
  dense_weight, sparse_weight
  model_limits
```

Every knob lands in **exactly one** tier; nothing straddles.

In Design 1 the *inferred* tier is populated by today's deterministic keyword/entity logic,
**refactored into one place** — not newly invented. `confidence` is present in the contract but
fixed (deterministic = trusted) until Design 2 introduces the hybrid classifier and the
3-level ladder.

---

## 3. The authority chain

```
Intent: requested   →   Policy: permitted   →   Infra: available
─────────────────────────────────────────────────────────────────
effective = requested ∧ permitted ∧ available
```

- **Intent** says what the query wants.
- **Policy** (`retrieval_breadth`) says how much work / evidence the user permits.
- **Infra** (`enable_*`) says what the system is allowed to run.

Execution features split into two classes, and the chain applies differently to each:

### 3.1 Intent-requested steps — `multi_hop`, `discovery`

```
use_multi_hop = needs_multi_hop          # intent: requested
             && breadth_permits_multi_hop # policy:  permitted
             && enable_multi_hop          # infra:   available
```

**Breadth is veto-only here.** Asymmetric semantics:
- `precise` **may suppress** exploratory/expensive steps (`breadth_permits_multi_hop = false`).
- `balanced` permits normal inferred steps.
- `broad` permits wider retrieval / larger budget / expansion / discovery behavior, **but does
  not invent `needs_multi_hop = true`** if intent did not infer it.
- `enable_* = false` (infra) can always veto.

### 3.2 Breadth-owned strategy — `use_hyde`, `use_query_expansion`

```
use_hyde            = breadth_sets_hyde       && enable_hyde
use_query_expansion = breadth_sets_expansion  && enable_query_expansion
```

These were **never intent's to request** — breadth is their legitimate *source*, not a vetoer.
Breadth turning expansion on is not "forcing intent" because there is no intent to force.
**Intent never touches these features.** There are deliberately no `needs_hyde` /
`needs_expansion` fields.

This dichotomy is what makes "breadth veto-only" precise rather than ambiguous.

### 3.3 Budget — shaped, not gated — `budget_tier`

```
budget_tier = f(retrieval_breadth, entity_scope, needs_synthesis)  # tight | standard | wide
```

`budget_tier` is neither an intent-requested step nor a pure breadth feature: it is a magnitude
*shaped* by both breadth (the dominant input) and intent-derived adaptiveness
(`entity_scope=broad` or `needs_synthesis=true` widen it). The veto-vs-force dichotomy does not
apply — there is no step to toggle, only a tier to select. This reproduces today's adaptive
budget; breadth sets the baseline tier and intent can widen it within what breadth permits, but
neither can exceed the global `model_limits` caps (infra).

---

## 4. Knob changes

### Gone
- **`discovery` flavor.** Discovery/multi-hop is inferred from the query, not selected as a
  breadth. (See §7 exception #1.)
- **`entity_mode = "multi_hop"`** as a field value. Execution path moves to
  `RoutingDecision.steps`. `entity_scope` describes the question's scope only.
- **Per-branch budget arithmetic** (`*2`, `min(…, 24)`, `min(…, 32)` scattered through the
  planner). Replaced by named tiers.

### Changed
- **`retrieval_flavor` → `retrieval_breadth`** (`precise | balanced | broad`). A pure
  precision↔recall dial. This is the one knob a user/admin still owns; explicit breadth always
  wins on width.
- **`use_hyde` / `use_query_expansion` / `use_multi_hop` → `enable_*` kill-switches** with
  veto-only semantics. They can suppress but never force; single authority per feature.
- **Budget → named tiers** (`tight | standard | wide`). Exact limits live behind the tier; the
  planner speaks in named policy. Tier selection is `f(breadth, entity_scope, needs_synthesis)`,
  reproducing today's adaptive-budget behavior.
- **`entity_mode` split** into `entity_scope` (classification: single | multi | broad | none)
  and `steps` (execution path, in the trace).

### Separate & preserved
- **`strict_evidence`** stays a distinct **answer-contract** knob, orthogonal to breadth:
  `breadth = precise` means "prefer narrow retrieval"; `strict_evidence = true` means "do not
  answer beyond supported evidence." They often correlate but are not the same promise.
  **Documentation note:** today's `exact` flavor suppresses entity→global fallback, which
  overlaps `strict_evidence`. The spec documents the split explicitly — breadth controls
  retrieval narrowness; `strict_evidence` controls answer fallback. The new `precise` breadth
  carries the retrieval-narrowness half; the fallback-on-no-evidence half stays with
  `strict_evidence`.

---

## 5. The `RoutingDecision` object

```
RoutingDecision {
  use_hyde
  use_query_expansion
  use_multi_hop
  budget_tier            # tight | standard | wide
  prompt_variant
  answer_shape           # requested_format or derive(needs_synthesis)
  steps                  # e.g. ["multi_hop"] — execution path taken
  reasons
  vetoes                 # e.g. ["precise breadth suppresses multi-hop"]
}
```

The object **is** the strategy — there is no separate `retrieval_strategy` enum sitting beside
its own parts. It is produced by **one pure function**:

```
derive_routing_decision(inferred, retrieval_breadth, config) -> RoutingDecision
```

This replaces the if/else ladder in `backend/app/rag/query/planner.py` (`build_query_plan`,
roughly lines 71–181). The function applies the authority chain (§3), records every suppression
in `vetoes`, and records why each feature is on/off in `reasons`.

`answer_shape` is **derived, not classified**: `requested_format or derive(needs_synthesis)`.
`requested_format` is a deterministic, high-precision extraction that lives in the *inferred*
tier, so the derived stage never re-scans the question (preserving "classify once").

---

## 6. Three-section trace

The trace mirrors the tiers, as separate blocks, so each stage is independently inspectable:

```
intent:
  needs_multi_hop: true
  reasons: ["discovery_keyword:哪些公司"]

policy:
  retrieval_breadth: precise
  permits_multi_hop: false
  vetoes: ["precise breadth suppresses multi-hop"]

infra:
  enable_multi_hop: true

routing_decision:
  use_multi_hop: false
  budget_tier: tight
  steps: ["retrieve_precise"]
  reasons: ["multi_hop vetoed by precise breadth"]
```

This is the part-1 observability object (`docs/prompt_reliability_implementation_plan.md`
§6 "Observability For Current Decisions"), now structured by tier. It plugs into the existing
`query_observability` payload / `query_run_stats` columns.

**Required unit assertions** (representative):
- `precise` + inferred `needs_multi_hop=true` → `policy.vetoes` non-empty,
  `routing_decision.use_multi_hop=false`.
- `broad` + no inferred discovery → `routing_decision.use_multi_hop=false` (breadth does not
  invent).
- `enable_multi_hop=false` + inferred `needs_multi_hop=true` + `broad` →
  `routing_decision.use_multi_hop=false` (infra veto).
- synthesis-marker query → `budget_tier` widens; no-marker single-entity query → `standard`.

---

## 7. Behavior-preservation contract

> **Design 1 is behavior-preserving except for explicitly listed force-semantics removed by the
> new authority chain. Any current flavor behavior that forces execution without inferred intent
> must either become an inferred intent rule or be listed as a measured behavior change.**

### Exception list (complete after a full flavor audit — one item)

1. **`discovery` flavor's forced `multi_hop=True` is removed.** Multi-hop now requires inferred
   discovery intent (the deterministic discovery-keyword gate in Design 1). Queries that
   selected `discovery` flavor but contain no discovery signal will no longer force multi-hop.
   Measured case-by-case on the golden set.

### Flavor audit (basis for the one-item list)

Rule applied: *does the current flavor force an execution step that intent would not otherwise
request?* Suppression and budget-setting are compatible with the new model; forcing an
intent-requested step is not.

| Flavor | Force-vs-veto verdict |
|---|---|
| `exact` → `precise` | All suppression + tight budget. Fallback suppression overlaps `strict_evidence` (documented in §4). No force. |
| `discovery` | Forces `multi_hop=True`. **Exception #1.** |
| `recall` → `broad` | Enables expansion = *breadth-owned* strategy, not a forced intent step. Wide budget. No force. |
| `balanced` | Adaptive budget driven by synthesis marker / broad entity = intent-derived `budget_tier`, preserved via tier mapping. No force. |

### Acceptance gate

- Golden-set **retrieval-only** Hit@5 / Hit@10 **identical** before/after.
- Golden-set **full** pass rate **identical** before/after.
- The **sole** permitted delta is the exception-#1 case set, explained case-by-case.
- All existing planner/observability unit tests pass; new tests assert the §6 trace shape.

---

## 8. Components & boundaries

| Unit | Responsibility | Depends on |
|---|---|---|
| `retrieval_breadth` resolution | map config → `precise/balanced/broad`; back-compat shim for old `retrieval_flavor` values (`exact→precise`, `recall→broad`, `discovery→broad`, `balanced→balanced`) | config |
| deterministic inferred-signal module | fold `_BROAD_SIGNALS`, `SYNTHESIS_QUERY_MARKERS`, `DISCOVERY_KEYWORDS`/`RESPONSIBILITY_HOP_KEYWORDS`, `requested_format` extraction, entity grounding into one function emitting the inferred tier | entity_confirm output |
| `budget_tier` resolver | `f(breadth, entity_scope, needs_synthesis) → tight/standard/wide`; tiers hold the concrete limits | inferred + breadth |
| `derive_routing_decision` | pure function applying the §3 authority chain → `RoutingDecision` | inferred, breadth, infra config |
| trace builder | emit the §6 three-section trace into the observability payload | RoutingDecision + tiers |

The deterministic inferred-signal module and `derive_routing_decision` are the two new pure
units; everything else is renaming/relocation. Three of the keyword sites collapse into one,
so the change is net-simplifying.

---

## 9. Non-goals

- No `QueryIntent` dataclass, no LLM classifier, no confidence ladder, no decision table beyond
  the deterministic `derive_routing_decision` (all Design 2).
- No retrieval-strategy retuning. Budget tiers must reproduce today's effective limits.
- No new keyword lists. The existing keyword sites are consolidated, not expanded.
- No UI redesign beyond surfacing `retrieval_breadth` in place of `retrieval_flavor`.
- No change to `strict_evidence` semantics or to model temperature/max-token settings
  (`9e43b2c`).

---

## 10. Open question deferred to Design 2

The `breadth_permits_*` predicates (which steps `precise` suppresses) are defined here for the
deterministic path. Design 2 must confirm the same predicates hold once intent is LLM-inferred
— specifically that a high-confidence inferred `needs_multi_hop` under `precise` still defers to
the suppress rule (policy beats intent), which the authority chain already guarantees.
