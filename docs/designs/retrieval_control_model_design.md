# Retrieval Control Model — Design

**Date:** 2026-06-12
**Status:** Shipped (Design 1 complete; discovery retirement deferred to Design 2)
**Source plan:** `prompt_reliability_implementation_plan.md` → "Requires Query-Intent Design" lane.
**Downstream consumer:** `query_intent_routing_roadmap.md` (Design 2 roadmap) →
`query_intent_2a_design.md` (Stage 2A).

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
  retrieval_breadth        # precise | balanced | broad | discovery(deprecated transitional)
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
  use_entity_fallback      # entity→global fallback when entity-filtered results are scarce or low-confidence
  budget_profile           # explicit limit set; see §3.3 mapping table
  prompt_variant
  answer_shape             # derive(needs_synthesis) in D1; requested_format override in D2
  steps                    # execution path, e.g. ["multi_hop"], ["multi_entity"]
  reasons
  vetoes

Infra caps (config, NEVER routing — veto-only; one exception: deprecated discovery bypasses enable_multi_hop, §3.2):
  enable_rerank
  enable_table_expand
  enable_context_expand
  enable_hyde
  enable_query_expansion
  enable_multi_hop
  dense_weight, sparse_weight
  model_limits
```

Every knob lands in **exactly one** tier; nothing straddles — with one named, visible exception:
`retrieval_breadth` carries a fourth **deprecated transitional** value, `discovery`. `precise |
balanced | broad` are clean breadth values (pure precision↔recall width). `discovery` is a
**preserved legacy task-profile** — it bundles task-type behavior that is not pure width — kept
verbatim so Design 1 changes nothing, and scheduled for removal in Design 2 once inferred
`needs_discovery` / `needs_multi_hop` exists to replace it (§7). We keep this one impurity
*visible* rather than hiding it behind a compatibility adapter.

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
- `enable_* = false` (infra) can always veto — **except** the deprecated `discovery` breadth,
  which bypasses `enable_multi_hop` (the one documented impurity, §3.2; removed in Design 2).

**Classify once, derive once — no second execution gate.** In Design 1, the deterministic
`needs_multi_hop` **is** today's `_decide_multi_hop` logic ([multi_hop.py:32-36](../../backend/app/rag/query/multi_hop.py#L32-L36)),
scope and keyword gates included — that logic moves into the *inferred* tier where it belongs.
`RoutingDecision.use_multi_hop` (the formula above) is then the **single** execution flag; the
pipeline reads it directly. Today's separate downstream gate (plan flag **and** a re-run of
`_decide_multi_hop` at [search_pipeline.py:88-91](../../backend/app/rag/query/search_pipeline.py#L88-L91))
collapses into this one derivation — the invariant requires it.

### 3.2 Breadth-owned strategy — `use_hyde`, `use_query_expansion`, `use_entity_fallback`

```
use_hyde            = breadth_sets_hyde       && enable_hyde && entity_scope != multi
use_query_expansion = breadth_sets_expansion  && enable_query_expansion
use_entity_fallback = entity_scope == single  && breadth_allows_fallback && not strict_evidence
```

Breadth is the *source* for these — **intent never sets them as a quality preference**; there are
deliberately no `needs_hyde` / `needs_expansion` fields. The one scope coupling is **structural,
not preference**: `entity_scope=multi` (multi-entity retrieval) suppresses HyDE because HyDE
cannot be split per entity ([hyde_search.py:52](../../backend/app/rag/query/hyde_search.py#L52),
`disabled_multi`). This is an **execution-compatibility veto** — a hard structural constraint
expressed as an explicit term in the formula above, *not* breadth or intent choosing HyDE off for
quality. Preserving today's `multi_explicit` behavior requires it; omitting it would let an
implementer keep the "clean" `use_hyde = breadth && enable` rule and silently regress multi-entity
retrieval.

`use_entity_fallback` (retry global search when entity-filtered results are **scarce or
low-confidence** — `REASON_LOW_SCORE_OR_INSUFFICIENT_HITS`, covering both the initial filtered
pass at [search.py:84](../../backend/app/rag/query/search.py#L84) and the post-rerank low-score path at
[search_pipeline.py](../../backend/app/rag/query/search_pipeline.py), not only the empty case) is a
**retrieval-width** behavior, so it is breadth-owned — `precise` suppresses it. It has a *second*
independent suppressor, `strict_evidence` (the answer contract); either can turn it off. This is
the §4 split made concrete: breadth owns retrieval width, `strict_evidence` owns answering.

**Applicable only when `entity_scope=single`** — the `entity_scope == single` term is a structural
guard, not a preference. Entity→global fallback needs an entity filter to fall back *from*, and
only `single` carries one: `multi_explicit` routes to per-entity search with no combined filter
([entity_confirm.py:79](../../backend/app/rag/query/entity_confirm.py#L79),
[search.py:48](../../backend/app/rag/query/search.py#L48)), and `broad`/`none` have no filter at all; the
post-rerank fallback path also requires a filter ([search_pipeline.py:198](../../backend/app/rag/query/search_pipeline.py#L198)).
For `multi | broad | none`, `use_entity_fallback` is a **no-op** regardless of breadth — the
formula returns `false`, matching today.

This dichotomy is what makes "breadth veto-only" precise rather than ambiguous.

**Breadth profile (grounded in current `planner.py` branches, behavior-preserving):**

| breadth | hyde | query_expansion | entity_fallback | permits multi-hop | from current flavor |
|---|---|---|---|---|---|
| `precise` | off | off | suppressed | no | `exact` |
| `balanced` | on (`enable_hyde`) | off | allowed unless `strict_evidence` | yes | `balanced` |
| `broad` | off | on (`enable_query_expansion`) | allowed unless `strict_evidence` | yes | `recall` |
| `discovery` *(deprecated)* | off | off | suppressed | **yes, bypassing `enable_multi_hop`** | `discovery` |

(`broad` doing *less* HyDE than `balanced` mirrors today's `recall`, which substitutes query
expansion for HyDE; preserved as-is.)

**The one visible impurity:** `discovery` permits multi-hop *and ignores the `enable_multi_hop`
infra veto* — the only place a breadth overrides infra, reproducing today's `discovery` flavor
forcing `use_multi_hop=True` past `cfg.use_multi_hop`. It remains subject to `needs_multi_hop`
(which folds in today's `_decide_multi_hop` scope+keyword logic — §3.1): multi-hop still does not
run on a keyword-less query, because `needs_multi_hop=false` there. This breach of the authority
chain is exactly why `discovery` is marked deprecated and removed in Design 2 — we keep it
labelled rather than hidden.

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
| `balanced`, single/multi/none, no-synth | `cfg.search_limit` | `cfg.hyde_limit` | `cfg.rrf_max_results` | `cfg.rerank_max_top_k` | `cfg.rerank_max_top_k` | 8000 | 5 | balanced default |
| `balanced`, scope=broad | `min(cfg.search_limit*2,24)` | `cfg.hyde_limit` | `min(cfg.rrf_max_results*2,32)` | `min(cfg.rerank_max_top_k*2,24)` | `min(cfg.rerank_max_top_k*2,8)` | 12000 | 5 | balanced broad |
| `balanced`, needs_synthesis | `min(max(cfg.search_limit*2,20),24)` | `cfg.hyde_limit` | 32 | `min(max(cfg.rerank_max_top_k*2,20),24)` | `cfg.rerank_max_top_k` | 10000 | 5 | balanced synthesis |
| `broad`, any | 20 | 0 | 40 | 30 | 8 | 14000 | 8 | `recall` |
| `discovery`, any *(deprecated)* | `cfg.search_limit` | 0 | `cfg.rrf_max_results` | `cfg.rerank_max_top_k` | `cfg.rerank_max_top_k` | 8000 | 5 | `discovery` |

`discovery` is its own profile row, distinct from `broad` — that is why it must remain a separate
breadth value, not be folded into `broad`. (Its prompt variant is `broad` *only when*
`entity_scope != multi`; see §3.4 for the precedence.)

**Modifier:** `entity_scope=multi` (today's `multi_explicit`) sets `per_entity_min_k=8`,
overriding whichever row's cell value — applied *after* profile selection, matching
[planner.py:159-160](../../backend/app/rag/query/planner.py#L159-L160). `entity_scope` values are
mutually exclusive (`single | multi | broad | none`), so a query selects exactly one budget row;
`scope=multi` co-occurring with `needs_synthesis` selects the synthesis row and *then* takes the
`per_entity_min_k=8` modifier. `scope=broad` and `scope=multi` cannot co-occur.

All cells pass through the existing global `_clamp_budget` caps (search≤40, rrf≤40,
rerank≤30, final≤30, ctx≤16000) = `model_limits` (infra). When `balanced`+broad and
`balanced`+synthesis both apply, broad wins (matches current precedence at
[planner.py:125-136](../../backend/app/rag/query/planner.py#L125-L136)).

The `tight | standard | wide` labels survive only as human-readable names for these rows; the
**table is the contract**.

### 3.4 Prompt variant — derived by precedence

`prompt_variant` is derived from `(entity_scope, breadth)` by a strict precedence that reproduces
[`_prompt_template`](../../backend/app/rag/query/planner.py#L225) exactly — **`entity_scope=multi` wins
first**:

```
prompt_variant = multi_entity   if entity_scope == multi
               = broad          elif breadth == discovery or entity_scope == broad
               = default        otherwise
```

The ordering matters and is easy to get wrong: a `discovery`-breadth query that *also* resolved
two explicit entities (`entity_scope=multi`) currently gets the **`multi_entity`** prompt, not
`broad` — and active `discovery` golden cases include exactly these two-entity comparisons. A
naive "discovery → broad" rule would regress them.

### 3.5 `entity_scope` structural constraints

`entity_scope` is an *inferred* classification, but it also carries **structural** constraints
that several derived features must honor — not preferences, but hard facts about what the
retrieval machinery can do. They are collected here so an implementer sees them together; each is
an explicit term in its feature's derivation, and **omitting any one silently regresses a current,
golden-tested behavior** (the recurring trap this spec guards against):

| Feature | Constraint | Why (structural) | Defined in |
|---|---|---|---|
| `use_hyde` | `… && entity_scope != multi` | HyDE cannot be split per entity (`disabled_multi`) | §3.2 |
| `use_entity_fallback` | `entity_scope == single && …` | only `single` carries an entity filter to fall back *from*; `multi/broad/none` have none | §3.2 |
| `prompt_variant` | `multi_entity` when `entity_scope == multi` (wins first) | multi-entity answers need the multi-entity template | §3.4 |
| `budget_profile` | `entity_scope == multi` → `per_entity_min_k=8` modifier | per-entity coverage floor for multi-entity retrieval | §3.3 |

These are the *only* places `entity_scope` reaches past pure classification into derivation. They
are structural compatibility terms, distinct from breadth (policy) and intent (preference); the
authority chain is unaffected.

---

## 4. Knob changes

### Gone
- **`entity_mode = "multi_hop"`** as a field value. Execution path moves to
  `RoutingDecision.steps`. `entity_scope` describes the question's scope only.
- **Per-branch budget arithmetic** (`*2`, `min(…, 24)`, `min(…, 32)` scattered through the
  planner). Replaced by the explicit `budget_profile` table (§3.3).

### Changed
- **`retrieval_flavor` → `retrieval_breadth`** (`precise | balanced | broad | discovery`). The
  first three are a pure precision↔recall dial; `discovery` is a **deprecated transitional**
  value retained verbatim (§2, §3.2). This is the one knob a user/admin still owns; explicit
  breadth always wins on width.
  - **Staged (Design 1 does the *internal* half only).** Design 1 keeps `QueryConfig.retrieval_flavor`
    as the source of truth and resolves it to an internal `retrieval_breadth` (`resolve_breadth`,
    §8); the legacy `query_plan["retrieval_flavor"]` value is retained verbatim so consumers, DB
    columns, the stats enum, and feedback are untouched. The **user-facing/stored rename** (config
    field, API models, DB, stats values `exact→precise` etc.) is a **deferred, separately-measured
    migration** — like discovery retirement — not part of the behavior-preserving Design 1.
- **`use_hyde` / `use_query_expansion` / `use_multi_hop` → `enable_*` kill-switches** with
  veto-only semantics. They can suppress but never force; single authority per feature (the lone
  exception is deprecated `discovery` bypassing `enable_multi_hop`, §3.2).
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
  *unconditionally* ([planner.py:79](../../backend/app/rag/query/planner.py#L79)), independent of
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
  use_entity_fallback    # entity_scope=single only; precise + strict_evidence each suppress
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

This is the part-1 observability object (`prompt_reliability_implementation_plan.md`
§6 "Observability For Current Decisions"), now structured by tier. It plugs into the existing
`query_observability` payload / `query_run_stats` columns.

**Required unit assertions** (representative):
- `precise` + inferred `needs_multi_hop=true` → `policy.vetoes` non-empty,
  `routing_decision.use_multi_hop=false`.
- `broad` + no inferred discovery → `routing_decision.use_multi_hop=false` (breadth does not
  invent).
- `enable_multi_hop=false` + inferred `needs_multi_hop=true` + `broad` →
  `routing_decision.use_multi_hop=false` (infra veto).
- `use_entity_fallback`: `single`+`balanced`+`strict_evidence=false` → `true`; `single`+`precise`
  → `false` (breadth); `single`+`balanced`+`strict_evidence=true` → `false` (answer contract);
  `multi`/`broad`/`none` → `false` regardless of breadth (no filter to fall back from).
- synthesis-marker query → `budget_profile` = balanced-synthesis row; no-marker single-entity query
  → balanced-default row; `entity_scope=multi` → `per_entity_min_k=8`.
- `retrieval_breadth=discovery` → the discovery profile (hyde off, expansion off, fallback off,
  8000-char budget, `broad` prompt **unless `entity_scope=multi`** — §3.4) and multi-hop permitted
  *even with* `enable_multi_hop=false` (the documented deprecated impurity), but only when
  `needs_multi_hop` is true (which folds in today's `_decide_multi_hop` scope+keyword logic).

---

## 7. Behavior-preservation contract

> **Design 1 is behavior-preserving. It introduces zero intended observable behavior changes.**
> Every current flavor maps 1:1 to a `retrieval_breadth` value (`discovery` is retained verbatim
> as a deprecated value), so no behavior is dropped, remapped, or smuggled into a rename. The one
> non-orthogonal current behavior — `discovery`'s task-type bundle — is kept *visible* as a
> labelled deprecated breadth, not hidden behind a compatibility adapter. Its retirement is
> Design 2 work, because removing it depends on the inferred `needs_discovery` that replaces it.

### Exception list — empty

There are no accepted behavior changes in Design 1. The four current flavors map one-to-one:
`exact→precise`, `balanced→balanced`, `recall→broad`, `discovery→discovery`.

### Flavor audit — traced through to execution

The audit traces each flavor through *plan flag → pipeline gate → search/execution*, not the
plan flag alone (the earlier draft's mistake). `use_multi_hop` on the plan does **not** force
execution: `_should_run_multi_hop` ([search_pipeline.py:88-91](../../backend/app/rag/query/search_pipeline.py#L88-L91))
also requires `_decide_multi_hop` ([multi_hop.py:32-36](../../backend/app/rag/query/multi_hop.py#L32-L36))
to pass (broad/none scope **and** a keyword).

| Flavor | Maps to | Behavior-preserving? |
|---|---|---|
| `exact` | `precise` | **Yes, exactly.** hyde off, expansion off, fallback off (permanent `precise` semantic — §4), multi-hop suppressed, tight budget, prompt per §3.4 (`default` unless `entity_scope`=multi/broad). |
| `recall` | `broad` | **Yes, exactly.** hyde off, expansion on(`cfg`), fallback-unless-strict, recall-wide budget. |
| `balanced` | `balanced` | **Yes, exactly.** Adaptive budget = `budget_profile` rows keyed on scope/synthesis. |
| `discovery` | `discovery` *(deprecated)* | **Yes, exactly** — retained as its own breadth profile (§3.2, §3.3), including the `enable_multi_hop`-bypass impurity, kept verbatim. |

**Correction recorded:** `discovery` flavor never *forced multi-hop execution* — execution was
always keyword-gated by `_decide_multi_hop`. Its only multi-hop effect is bypassing the
`cfg.use_multi_hop` config gate (now `enable_multi_hop`). Retaining `discovery` as a breadth
preserves that bypass verbatim; the impurity is documented in §3.2, not silently changed.

### Deferred to Design 2: discovery retirement

Removing the `discovery` breadth value is Design 2 work, because it requires inferred
`needs_discovery` / `needs_multi_hop` to take over. When that lands, `discovery` selections become
*native* breadth + inferred intent, and each resulting delta is measured before the value is
deleted: budget (8000 → ?), expansion (off → ?), fallback (off → ?), prompt (broad → ?), and the
`enable_multi_hop` bypass (removed — the infra veto begins to apply). None of that happens in
Design 1.

### Acceptance gate

- Golden-set **retrieval-only** Hit@5 / Hit@10 **identical** before/after — **no permitted delta**.
- Golden-set **full** pass rate **identical** before/after, including the active `discovery`
  golden cases (`data/challenge_golden_set_v1.jsonl`).
- A targeted test exercises a `discovery`-breadth query and asserts the profile + `enable_multi_hop`
  bypass reproduce pre-refactor routing exactly.
- All existing planner/observability unit tests pass; new tests assert the §6 trace shape.

---

## 8. Components & boundaries

| Unit | Responsibility | Depends on |
|---|---|---|
| `resolve_breadth` | `config → retrieval_breadth`. Renames the four flavor values 1:1: `exact→precise`, `recall→broad`, `balanced→balanced`, `discovery→discovery`. No tag, no tuple, no compat block. | config |
| deterministic inferred-signal module | fold `_BROAD_SIGNALS`, `SYNTHESIS_QUERY_MARKERS`, `DISCOVERY_KEYWORDS`/`RESPONSIBILITY_HOP_KEYWORDS`, entity grounding into one function emitting the inferred tier. `requested_format` is **out of scope in Design 1** (always null). | entity_confirm output |
| `budget_profile` resolver | select the §3.3 table row from `(breadth, entity_scope, needs_synthesis)`; apply the `entity_scope=multi` per-entity modifier; pass through `_clamp_budget`. Row values are the contract. | inferred + breadth |
| `entity_scope` compatibility | today's `multi_explicit` → `entity_scope=multi` + `steps=["multi_entity"]`; from it derive per-entity search ([search.py:48](../../backend/app/rag/query/search.py#L48)), HyDE-disable ([hyde_search.py:52](../../backend/app/rag/query/hyde_search.py#L52)), `multi_entity` prompt, and `per_entity_min_k=8` — preserving all four current effects of `multi_explicit` | entity_confirm output |
| `derive_routing_decision` | pure function applying the §3 authority chain → `RoutingDecision`; the `discovery` breadth row carries the documented `enable_multi_hop`-bypass impurity | inferred, breadth, infra config |
| trace builder | emit the §6 three-section trace into the observability payload | RoutingDecision |

> **Caveat — `discovery` is a real breadth value, not an alias for `broad`.** It has its own
> profile row (§3.2, §3.3) and its own `enable_multi_hop`-bypass behavior. A future reader must
> not "simplify" by folding `discovery` into `broad` — they are intentionally different. The
> value is removed only by the Design 2 discovery retirement (§7), after its inferred replacement
> exists and each delta is measured.

The deterministic inferred-signal module and `derive_routing_decision` are the two new pure
units; everything else is renaming/relocation. Three of the keyword sites collapse into one,
so the change is net-simplifying. There is **no** compatibility adapter — the single impurity
(`discovery`) lives as a labelled breadth value, visible in config, trace, and tests.

---

## 9. Non-goals

- No `QueryIntent` dataclass, no LLM classifier, no confidence ladder, no decision table beyond
  the deterministic `derive_routing_decision` (all Design 2).
- No retrieval-strategy retuning. The `budget_profile` table must reproduce today's effective
  limits exactly.
- No new keyword lists. The existing keyword sites are consolidated, not expanded.
- No `requested_format` extraction (Design 2). `answer_shape` derives from `needs_synthesis` only.
- No removal of the `discovery` breadth value — its retirement is Design 2 work (§7), once
  inferred discovery replaces it. Design 1 keeps it as a labelled deprecated value.
- No user-facing/stored rename of `retrieval_flavor` in Design 1. The rename is *internal only*
  (config → `retrieval_breadth` resolution); the external config field, API, DB, stats values, and
  UI label stay `retrieval_flavor` until a later deferred migration (see §4 Changed, staged note).
- No change to `strict_evidence` semantics or to model temperature/max-token settings
  (`9e43b2c`).

---

## 10. Open question deferred to Design 2

The `breadth_permits_*` predicates (which steps `precise` suppresses) are defined here for the
deterministic path. Design 2 must confirm the same predicates hold once intent is LLM-inferred
— specifically that a high-confidence inferred `needs_multi_hop` under `precise` still defers to
the suppress rule (policy beats intent), which the authority chain already guarantees.
