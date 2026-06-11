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
  requested_format         # table | bullets | prose | null  — Design 2 only; always null in D1
  confidence               # (Design 2; in Design 1 always "high"/deterministic)
  reasons                  # list[str]

Derived (RoutingDecision — the strategy object):
  use_hyde
  use_query_expansion
  use_multi_hop
  use_entity_fallback      # entity→global fallback when entity-filtered search is empty
  budget_profile           # explicit limit set; see §3.3 mapping table
  prompt_variant
  answer_shape             # derive(needs_synthesis) in D1; requested_format override in D2
  steps                    # execution path, e.g. ["multi_hop"], ["multi_entity"]
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
3-level ladder. `requested_format` is reserved in the contract but **always `null` in Design 1**
— scanning the query for "give me a table" / "列出" is *new* inference and belongs to Design 2;
in Design 1 `answer_shape` derives solely from `needs_synthesis`, reproducing today's
template-driven shape.

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

### 3.2 Breadth-owned strategy — `use_hyde`, `use_query_expansion`, `use_entity_fallback`

```
use_hyde            = breadth_sets_hyde       && enable_hyde
use_query_expansion = breadth_sets_expansion  && enable_query_expansion
use_entity_fallback = breadth_allows_fallback && not strict_evidence    # two independent suppressors
```

These were **never intent's to request** — breadth is their legitimate *source*, not a vetoer.
Breadth turning expansion on is not "forcing intent" because there is no intent to force.
**Intent never touches these features.** There are deliberately no `needs_hyde` /
`needs_expansion` fields.

`use_entity_fallback` (retry global search when an entity-filtered search returns nothing) is a
**retrieval-width** behavior, so it is breadth-owned — `precise` suppresses it. It has a *second*
independent suppressor, `strict_evidence` (the answer contract); either can turn it off. This is
the §4 split made concrete: breadth owns retrieval width, `strict_evidence` owns answering.

This dichotomy is what makes "breadth veto-only" precise rather than ambiguous.

**Breadth profile (grounded in current `planner.py` branches, behavior-preserving):**

| breadth | hyde | query_expansion | entity_fallback | permits multi-hop | from current flavor |
|---|---|---|---|---|---|
| `precise` | off | off | suppressed | no | `exact` |
| `balanced` | on (`enable_hyde`) | off | allowed unless `strict_evidence` | yes | `balanced` |
| `broad` | off | on (`enable_query_expansion`) | allowed unless `strict_evidence` | yes | `recall` |

(`broad` doing *less* HyDE than `balanced` mirrors today's `recall`, which substitutes query
expansion for HyDE; preserved as-is.)

### 3.3 Budget — shaped, not gated — `budget_profile`

Budget is neither an intent-requested step nor a pure breadth feature: it is a limit set
*shaped* by breadth (dominant) and intent-derived adaptiveness (`entity_scope` / `needs_synthesis`
widen it within what breadth permits). The veto-vs-force dichotomy does not apply — there is no
step to toggle. To make the §7 acceptance gate testable, the profile is an **explicit mapping
table** reproducing each current `planner.py` branch exactly (not three vague tiers). Limits are
the current symbolic values; `cfg.*` = today's `QueryConfig` defaults:

| `(breadth, scope, synthesis)` → profile | search | hyde | rrf_top_k | rerank_cand | final_k | ctx_chars | per_entity_min_k | current branch |
|---|---|---|---|---|---|---|---|---|
| `precise`, any | 8 | 0 | 8 | 8 | 3 | 5000 | 3 | `exact` |
| `balanced`, single/none, no-synth | `cfg.search_limit` | `cfg.hyde_limit` | `cfg.rrf_max_results` | `cfg.rerank_max_top_k` | `cfg.rerank_max_top_k` | 8000 | 5 | balanced default |
| `balanced`, scope=broad | `min(cfg.search_limit*2,24)` | `cfg.hyde_limit` | `min(cfg.rrf_max_results*2,32)` | `min(cfg.rerank_max_top_k*2,24)` | `min(cfg.rerank_max_top_k*2,8)` | 12000 | balanced broad |
| `balanced`, needs_synthesis | `min(max(cfg.search_limit*2,20),24)` | `cfg.hyde_limit` | 32 | `min(max(cfg.rerank_max_top_k*2,20),24)` | `cfg.rerank_max_top_k` | 10000 | 5 | balanced synthesis |
| `broad`, any | 20 | 0 | 40 | 30 | 8 | 14000 | 8 | `recall` |

**Modifier:** `entity_scope=multi` (today's `multi_explicit`) sets `per_entity_min_k=8`,
overriding the cell value — applied after profile selection, matching
[planner.py:159-160](backend/app/rag/query/planner.py#L159-L160).

All cells pass through the existing global `_clamp_budget` caps (search≤40, rrf≤40,
rerank≤30, final≤30, ctx≤16000) = `model_limits` (infra). When `balanced`+broad and
`balanced`+synthesis both apply, broad wins (matches current precedence at
[planner.py:125-136](backend/app/rag/query/planner.py#L125-L136)).

The `tight | standard | wide` labels survive only as human-readable names for these rows; the
**table is the contract**.

---

## 4. Knob changes

### Gone
- **`discovery` flavor** as a user-selectable knob. Discovery/multi-hop becomes inferred (Design
  2). Legacy `discovery` configs are **not silently remapped** — they resolve to
  `retrieval_breadth=broad` **plus** `legacy_flavor_origin="discovery"`, and a named compat block
  reproduces the old bundle exactly until a later measured migration removes it (§7, §8). No
  observable change in Design 1.
- **`entity_mode = "multi_hop"`** as a field value. Execution path moves to
  `RoutingDecision.steps`. `entity_scope` describes the question's scope only.
- **Per-branch budget arithmetic** (`*2`, `min(…, 24)`, `min(…, 32)` scattered through the
  planner). Replaced by the explicit `budget_profile` table (§3.3).

### Changed
- **`retrieval_flavor` → `retrieval_breadth`** (`precise | balanced | broad`). A pure
  precision↔recall dial. This is the one knob a user/admin still owns; explicit breadth always
  wins on width.
- **`use_hyde` / `use_query_expansion` / `use_multi_hop` → `enable_*` kill-switches** with
  veto-only semantics. They can suppress but never force; single authority per feature.
- **Budget → explicit `budget_profile` mapping table** (§3.3). Concrete limits live in the
  table, keyed on `(breadth, entity_scope, needs_synthesis)`, reproducing each current branch
  exactly. The `tight/standard/wide` labels are names for table rows, not the contract.
- **`entity_mode` split** into `entity_scope` (classification: single | multi | broad | none)
  and `steps` (execution path, in the trace). Today's `multi_explicit` → `entity_scope=multi`
  + `steps=["multi_entity"]` (see §8 for the full compatibility shape).

### Separate & preserved
- **`strict_evidence`** stays a distinct **answer-contract** knob: "do not answer beyond
  supported evidence." It is **not** the owner of entity→global fallback — that fallback is a
  *retrieval-width* behavior owned by **breadth** (`precise` suppresses it; see §3.2). The two
  are independent suppressors of `use_entity_fallback`: either `precise` *or* `strict_evidence`
  turns it off. This corrects the earlier framing — today's `exact` disables fallback
  *unconditionally* ([planner.py:79](backend/app/rag/query/planner.py#L79)), independent of
  `strict_evidence`, so mapping `exact→precise` only stays behavior-preserving **because
  `precise` itself suppresses fallback**. Without that rule, old `exact` queries with
  `strict_evidence=false` would begin falling back globally — a regression. `breadth=precise`
  means "prefer narrow retrieval (no global widening)"; `strict_evidence=true` means "refuse to
  answer without evidence." They often correlate but are different promises.

---

## 5. The `RoutingDecision` object

```
RoutingDecision {
  use_hyde
  use_query_expansion
  use_multi_hop
  use_entity_fallback    # breadth-owned; precise suppresses; strict_evidence also suppresses
  budget_profile         # explicit limit set from the §3.3 table
  prompt_variant
  answer_shape           # derive(needs_synthesis) in D1
  steps                  # e.g. ["multi_hop"], ["multi_entity"] — execution path taken
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

`answer_shape` is **derived, not classified**. In Design 1 it is `derive(needs_synthesis)`
(reproducing today's template-driven shape). In Design 2 an explicit `requested_format` from the
*inferred* tier overrides it — `requested_format or derive(needs_synthesis)` — so even the
override is classified once, never re-scanned in the derived stage.

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
  use_entity_fallback: false
  budget_profile: precise
  steps: ["retrieve_precise"]
  reasons: ["multi_hop vetoed by precise breadth", "fallback suppressed by precise breadth"]
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
- `precise` → `use_entity_fallback=false` regardless of `strict_evidence`; `balanced`+`strict_evidence=true`
  → `use_entity_fallback=false`; `balanced`+`strict_evidence=false` → `true`.
- synthesis-marker query → `budget_profile` = balanced-synthesis row; no-marker single-entity query
  → balanced-default row; `entity_scope=multi` → `per_entity_min_k=8`.
- `legacy_flavor_origin="discovery"` → the discovery compat bundle (hyde off, expansion off,
  fallback off, 8000-char budget, broad prompt) regardless of native `broad` defaults.

---

## 7. Behavior-preservation contract

> **Design 1 is behavior-preserving. It introduces zero intended observable behavior changes.**
> Any current flavor behavior that a single `retrieval_breadth` cannot reproduce is preserved by
> a named, deletable `legacy_flavor_origin` compatibility block, not silently dropped or remapped.
> Behavior deltas are deferred to a later, separately-measured migration — never smuggled into
> Design 1's renames.

### Exception list — empty

There are no accepted behavior changes in Design 1. (The earlier "discovery loses forced
multi-hop" entry was withdrawn: it was based on reading plan flags rather than the execution
path. See the audit below.)

### Flavor audit — traced through to execution

The audit traces each flavor through *plan flag → pipeline gate → search/execution*, not the
plan flag alone — the earlier draft's mistake. `use_multi_hop` on the plan does **not** force
execution: `_should_run_multi_hop` ([search_pipeline.py:88-91](backend/app/rag/query/search_pipeline.py#L88-L91))
also requires `_decide_multi_hop` ([multi_hop.py:32-36](backend/app/rag/query/multi_hop.py#L32-L36))
to pass (broad/none scope **and** a keyword).

| Flavor | Maps to | Reproducible by breadth alone? |
|---|---|---|
| `exact` | `precise` | **Yes.** hyde off, expansion off, fallback off (permanent `precise` semantic — §4), multi-hop suppressed, tight budget, default prompt. No tag. |
| `recall` | `broad` | **Yes.** hyde off, expansion on(`cfg`), fallback-unless-strict, recall-wide budget. No tag. |
| `balanced` | `balanced` | **Yes.** Adaptive budget = `budget_profile` table rows keyed on scope/synthesis. No tag. |
| `discovery` | `broad` **+ tag** | **No.** Bundle (hyde off, expansion off, fallback off, *8000* budget, *broad* prompt, multi-hop config-gate bypass) maps to no single breadth → `legacy_flavor_origin="discovery"` compat block reproduces it. |

**Correction recorded:** `discovery` flavor never *forced multi-hop execution* — execution was
always keyword-gated by `_decide_multi_hop`. Its only multi-hop effect was bypassing the
`cfg.use_multi_hop` config gate; under the new model the `enable_multi_hop` infra veto would
instead apply. That difference (and the hyde/expansion/fallback/budget/prompt deltas of moving
`discovery` to *native* `broad`) is precisely what the compat block freezes and the deferred
migration measures.

### Deferred: legacy-discovery migration (NOT in Design 1)

A later, separately-measured change deletes the `legacy_flavor_origin="discovery"` compat block,
promoting legacy-discovery configs to *native* `broad`. Each delta is measured before promotion:
budget (8000 → recall-wide), expansion (off → on), fallback (off → on-unless-strict), prompt
(broad → default), multi-hop gating (config-bypass → infra-veto). Until then **native `broad` and
legacy-discovery-origin `broad` are intentionally different** — see the §8 caveat. Design 2's
inferred discovery may also change where discovery-type queries "land," so the eventual target is
revisited there.

### Acceptance gate

- Golden-set **retrieval-only** Hit@5 / Hit@10 **identical** before/after — **no permitted delta**.
- Golden-set **full** pass rate **identical** before/after.
- A targeted test exercises a stored `discovery` config and asserts the compat bundle reproduces
  pre-refactor routing exactly.
- All existing planner/observability unit tests pass; new tests assert the §6 trace shape.

---

## 8. Components & boundaries

| Unit | Responsibility | Depends on |
|---|---|---|
| `resolve_breadth` | `config → (retrieval_breadth, legacy_flavor_origin)`. Maps `exact→precise`, `recall→broad`, `balanced→balanced` with **no** tag; maps `discovery→broad` **with** `legacy_flavor_origin="discovery"`. The new model reads **only** `retrieval_breadth`. | config |
| legacy compat block | keyed on `legacy_flavor_origin=="discovery"`, reproduces the discovery bundle (hyde off, expansion off, fallback off, 8000 budget, broad prompt, multi-hop config-bypass). Named and isolated so a later migration deletes it wholesale. | `resolve_breadth` |
| deterministic inferred-signal module | fold `_BROAD_SIGNALS`, `SYNTHESIS_QUERY_MARKERS`, `DISCOVERY_KEYWORDS`/`RESPONSIBILITY_HOP_KEYWORDS`, entity grounding into one function emitting the inferred tier. `requested_format` is **out of scope in Design 1** (always null). | entity_confirm output |
| `budget_profile` resolver | select the §3.3 table row from `(breadth, entity_scope, needs_synthesis)`; apply the `entity_scope=multi` per-entity modifier; pass through `_clamp_budget`. Row values are the contract. | inferred + breadth |
| `entity_scope` compatibility | today's `multi_explicit` → `entity_scope=multi` + `steps=["multi_entity"]`; from it derive per-entity search ([search.py:48](backend/app/rag/query/search.py#L48)), HyDE-disable ([hyde_search.py:52](backend/app/rag/query/hyde_search.py#L52)), `multi_entity` prompt, and `per_entity_min_k=8` — preserving all four current effects of `multi_explicit` | entity_confirm output |
| `derive_routing_decision` | pure function applying the §3 authority chain → `RoutingDecision` (incl. legacy compat block) | inferred, breadth, `legacy_flavor_origin`, infra config |
| trace builder | emit the §6 three-section trace into the observability payload | RoutingDecision |

> **Caveat — do not collapse the compat block.** Native `broad` and legacy-discovery-origin
> `broad` resolve to the *same* `retrieval_breadth` but are **intentionally different** during the
> shim (the discovery bundle vs clean broad). A future reader must not "simplify" by deleting the
> `legacy_flavor_origin` branch on the grounds that both are `broad`. The branch is removed only
> by the deferred, measured migration in §7.

The deterministic inferred-signal module and `derive_routing_decision` are the two new pure
units; everything else is renaming/relocation. Three of the keyword sites collapse into one,
so the change is net-simplifying.

---

## 9. Non-goals

- No `QueryIntent` dataclass, no LLM classifier, no confidence ladder, no decision table beyond
  the deterministic `derive_routing_decision` (all Design 2).
- No retrieval-strategy retuning. The `budget_profile` table must reproduce today's effective
  limits exactly.
- No new keyword lists. The existing keyword sites are consolidated, not expanded.
- No `requested_format` extraction (Design 2). `answer_shape` derives from `needs_synthesis` only.
- No deletion of the `legacy_flavor_origin="discovery"` compat block — that is the deferred,
  separately-measured migration (§7), not part of Design 1.
- No UI redesign beyond surfacing `retrieval_breadth` in place of `retrieval_flavor` (legacy
  `discovery` selections continue to resolve via the compat path).
- No change to `strict_evidence` semantics or to model temperature/max-token settings
  (`9e43b2c`).

---

## 10. Open question deferred to Design 2

The `breadth_permits_*` predicates (which steps `precise` suppresses) are defined here for the
deterministic path. Design 2 must confirm the same predicates hold once intent is LLM-inferred
— specifically that a high-confidence inferred `needs_multi_hop` under `precise` still defers to
the suppress rule (policy beats intent), which the authority chain already guarantees.
