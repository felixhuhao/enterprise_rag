# Retrieval Redesign Codepath Cleanup Audit

**Date:** 2026-06-13
**Scope:** Codepaths left unexercised, redundant, or orphaned after the retrieval
control model redesign (Design 1) and query-intent routing rollout (Design 2,
Stages 2A–2D).
**Audit snapshot baseline:** `614 passed` unit suite; all design stages shipped per
`query_intent_routing_roadmap.md`.

---

## Context

The redesign replaced a flat planner knob namespace with a four-tier authority
chain (preference → inferred → derived → infra). Key structural changes:

- **Design 1:** `planner.py` if/else ladder → `control/{breadth,budget,inferred,routing}.py`.
  Separate downstream multi-hop gate collapsed into a single `RoutingDecision.use_multi_hop`.
- **Design 2A–2C:** Graded confidence ladder, trust gate, inline LLM classifier,
  trust-gated activation (now live and default-on).
- **Design 2D:** `discovery` breadth retired → maps to `balanced`; inferred
  `needs_discovery` takes over; `use_multi_hop` default flipped to `true`.

Each stage left scaffolding or duplicated logic behind. This audit catalogues
every cleanup candidate, organized by removal safety.

---

## Tier 1 — Dead in Query-Serving Path

These codepaths have **zero query-serving callers**. Their only remaining
consumers are tests, offline gate tools, operational reporting scripts, or
nothing at all.

Do not treat every Tier 1 item as delete-now. Split them by retention status:

- **Completed:** `_decide_multi_hop()` (§1.1) was deleted and tests now cover
  `infer_signals(...).needs_multi_hop`; write-only `proposal_execution`
  (§1.2) was deleted from `inline_shadow`; completed `compare_activation_eval.py`
  gate tooling (§1.4) was archived; single-decision `trust_gate()` (§1.3) was
  replaced by the canonical bundle gate.
- **Archive only after operational sign-off:** offline/regression tools
  (`route_scoring.py`, `score_routing_golden_set.py`) and post-flip watch
  fields used by `report_inline_shadow.py`.

### 1.1 `_decide_multi_hop()` — superseded by the inferred tier

| | |
|---|---|
| **Location** | `backend/app/rag/query/multi_hop.py:32-36` |
| **Status** | Complete — deleted in `82add5a` |
| **Remaining consumers** | None |

The multi-hop decision rule (`scope in ("broad","none") and discovery keyword`)
was folded into `control/inferred.py:59` as the `needs_multi_hop` signal. The
pipeline gate `should_run_multi_hop_from_plan` reads only
`plan.get("use_multi_hop")`, which originates from
`RoutingDecision.use_multi_hop` (`routing.py:59`). The old two-gate structure
(plan flag **and** a re-run of `_decide_multi_hop`) collapsed into one
derivation, exactly as Design 1 §3.1 specified.

**Action:** Done. `test_multi_hop.py` assertions now test
`infer_signals(...).needs_multi_hop`.

---

### 1.2 Shadow-only `inline_shadow` comparison fields

| | |
|---|---|
| **Location** | `backend/app/rag/query/control/routing.py:113-130` (`build_inline_shadow`) |
| **Status** | No live-query behavioral dependence |
| **Remaining consumers** | Operational reporting / offline gate scripts + their tests (see 1.4) |

Two comparison fields remain in `routing_trace.inline_shadow`:

| Field | Produced at | Read by |
|---|---|---|
| `proposal_diverged` | `routing.py:114,129` | `report_inline_shadow.py:37,51`; `test_control_routing.py`; `test_inline_shadow_report.py` |
| `activatable_diverged` | `routing.py:130` | `report_inline_shadow.py:36,52,94,106`; `test_control_routing.py`; `test_query_planner.py:215,288` |

No live query-serving code branches on any of these. The trust gate uses the
`activatable()` predicate directly via `trust_gate_bundle()`, not these fields.
The design explicitly schedules their deletion:

> Delete shadow-only comparison fields when they stop serving operational audits:
> `proposal_execution`, `proposal_diverged`, `activatable_diverged`.
> — `query_intent_2d_design.md §2`

`proposal_execution` was deleted because it was write-only. The other two
require retiring or replacing their reporting/gate-script consumers first (§1.4).

---

### 1.3 `trust_gate()` single-decision version

| | |
|---|---|
| **Location** | Formerly `backend/app/rag/query/control/routing.py:89-95` |
| **Status** | Complete — deleted |
| **Remaining consumers** | None |

The active inline seam uses `trust_gate_bundle()` (`planner.py:149`), which
operates on whole `(intent, decision, budget)` tuples. The single-decision
`trust_gate()` survived only because the offline golden-set scorer reproduced
the canonical 2C-1 gate through it. It carried zero active-path weight.

**Action:** Done. `score_routing_golden_set.py` now uses `trust_gate_bundle()`
directly, matching the active planner seam.

---

### 1.4 Offline activation-gate / reporting scripts

| | |
|---|---|
| **Location** | `backend/scripts/report_inline_shadow.py`; formerly `backend/scripts/compare_activation_eval.py` |
| **Status** | `compare_activation_eval.py` archived; `report_inline_shadow.py` still useful post-flip watch tooling |
| **Remaining consumers** | `report_inline_shadow.py` unit tests |

Both were built around the 2C-2/2C-3 activation decision, but they no longer
have the same removal status.

`compare_activation_eval.py` was a completed 2C-3 gate comparator:

> `compare_activation_eval.py` — standalone, archived after the flip like the
> other gate tools.
> — `query_intent_2c3_design.md §227`

It has been deleted with its dedicated tests. `report_inline_shadow.py` is
different. It is still the lightweight post-flip
operational watch tool until replacement active-path reporting exists:

> Archive `scripts/report_inline_shadow.py` only after replacement active-path
> reporting exists.
> — `query_intent_2d_design.md §2`

The flips shipped (2D complete), but `report_inline_shadow.py` remains the
reason to keep `proposal_diverged` / `activatable_diverged` (§1.2) for now.

**Note:** `scripts/replay_intent_classifier.py` recomputes its own
`activatable_diverged` equivalent locally and does **not** read the persisted
shadow fields. It belongs to the same offline-intent-eval family and is a
candidate for the same archival, but has no hard dependency on the shadow fields.

---

### 1.5 `route_scoring.py` — offline scoring module

| | |
|---|---|
| **Location** | `backend/app/rag/query/control/route_scoring.py` (177 lines) |
| **Status** | Offline-only |
| **Remaining consumers** | `scripts/score_routing_golden_set.py:15-20`; `test_route_scoring.py` |

Not re-exported from `control/__init__.py`. Not imported by any `backend/app/`
module. The design explicitly states:

> It is not an import from `control/route_scoring.py` — that module is offline
> scoring.
> — `query_intent_2c2_design.md §95`

**Action:** If the routing golden-set scorer is no longer run operationally or
as a regression check, this module and its tests can be archived. If the scorer
remains useful as a regression tool, leave in place.

---

## Tier 2 — Redundant / Should Consolidate

These codepaths are live but duplicate logic that already exists elsewhere in
the new control model. They are correctness/maintainability risks, not dead
code.

### 2.1 `legacy_use_hyde` recomputation — latent correctness drift

| | |
|---|---|
| **Location** | Formerly `backend/app/rag/query/planner.py:166` |
| **Risk** | Complete — fixed in `82add5a` |

```python
# planner.py:166 — what the plan carries
legacy_use_hyde = BREADTH_PROFILES[breadth].sets_hyde and cfg.use_hyde

# routing.py:53 — what the RoutingDecision carries (correct)
use_hyde = profile.sets_hyde and cfg.use_hyde and scope != "multi"
```

`_plan_from_routing` receives the `RoutingDecision` object and uses
`decision.use_query_expansion` and `decision.use_multi_hop` directly (lines
173-174) — **but recomputes HyDE from scratch** instead of reading
`decision.use_hyde`. The recomputation silently dropped the `scope != "multi"`
guard from Design 1 §3.2.

The missing guard is currently patched by a separate runtime check in
`hyde_search.py` (`if state.get("entity_mode") == "multi_explicit": return
disabled_multi`; currently around lines 85-86). Without that compensating
control, multi-entity queries would incorrectly run HyDE.

**Action:** Done. `_plan_from_routing` now reads `decision.use_hyde`; the
`hyde_search.py` guard remains as defense-in-depth.

---

### 2.2 Duplicate `_should_run_multi_hop`

| | |
|---|---|
| **Location** | Formerly `search_pipeline.py:88-89` and `retrieval_test_service.py:160-161` |
| **Status** | Complete — consolidated into `should_run_multi_hop_from_plan` |

The former duplicated bodies were both `return bool(plan.get("use_multi_hop"))`.
The `ShouldRunMultiHopFn` type alias still carries a `query: str` parameter
that the shared implementation does not use — retained for DI signature
compatibility.

**Action:** Done. `search_pipeline.py` owns the shared default;
`retrieval_test_service.py` aliases it. The `query` parameter remains for DI
signature compatibility.

---

### 2.3 Flavor valid-set duplicated in 4+ places

| Location | Form |
|---|---|
| **Status** | Complete — centralized in `config.py` |
| **Canonical source** | `RETRIEVAL_FLAVORS`, `VALID_RETRIEVAL_FLAVORS`, `normalize_retrieval_flavor` |

The accepted legacy values are now defined once in `app.rag.query.config` and
reused by planner, query config clamping, query stats, admin eval, feedback
drafting, and golden-set eval summary/normalization. `discovery` remains in the
accepted set intentionally for compatibility.

**Action:** Done. Final removal of `discovery` from the accepted external API
is still a separate compatibility migration.

---

### 2.4 `_clamp_budget` + constants — co-location smell

| | |
|---|---|
| **Location** | Formerly `planner.py:18-20` (constants), `planner.py:181-189` (function) |
| **Status** | Complete — moved to `control/budget.py` |

The three infra-cap constants (`MAX_SEARCH_LIMIT = 40`,
`MAX_RERANK_CANDIDATES = 30`, `MAX_CONTEXT_CHARS = 16000`) and the
`_clamp_budget` function formerly lived in `planner.py` but were consumed
exclusively by `control/budget.py`. That created a `planner → budget`
back-reference through a private symbol
(`from app.rag.query.planner import _clamp_budget`).

**Action:** Done. `_clamp_budget` and the three cap constants now live in
`control/budget.py`, removing the cross-module private import.

---

## Tier 3 — Semantic Coupling / Design Debt

These items require behavioral analysis before removal. They are not dead, but
they represent unfinished design migrations.

### 3.1 `entity_mode = "multi_hop"` live producer/consumer pair

| | |
|---|---|
| **Producer** | Formerly `multi_hop.py` — `"entity_mode": "multi_hop"` |
| **Consumer** | Formerly `validate_citations.py` — `state.get("entity_mode") == "multi_hop"` |
| **Design says** | §4: *"`entity_mode = "multi_hop"` as a field value. Execution path moves to `RoutingDecision.steps`."* |
| **Status** | Complete — multi-hop execution is represented by `hop_plan` / `search_mode`, not `entity_mode` |

These formerly formed a coupled live pair: `multi_hop.py` writes the value into
state, and `validate_citations.py` read it to gate the context-citation
fallback. The `state.py:14` type annotation (`single | multi_explicit | broad |
none`) does not even list `multi_hop`.

The same fallback was also triggered by `hop_plan == "discovery"`, which covers
the current multi-hop execution case through a more explicit signal. Citation
validation now relies on `hop_plan == "discovery"` only; tests characterize
that `entity_mode="multi_hop"` alone does not trigger fallback. Multi-hop
success now preserves the original entity scope in `entity_mode`; visible
retrieval-test labeling derives "关联查找" from `hop_plan` / `search_mode`.

**Action:** Done. `entity_mode` is again scope-only; multi-hop execution remains
observable through `hop_plan="discovery"`, `search_mode="multi_hop*"`, and
`hop_trace`.

---

### 3.2 `diversify_context.py` reads `retrieval_flavor` not `breadth`

| | |
|---|---|
| **Location** | Formerly `diversify_context.py:16,24,44` |
| **Design says** | §3.2: breadth owns retrieval-width behavior |
| **Status** | Complete — diversification now keys on `retrieval_breadth` |

```python
_DIVERSIFY_FLAVORS = {"recall"}                          # line 16
flavor = plan.get("retrieval_flavor", cfg.retrieval_flavor)  # line 24
if flavor in _DIVERSIFY_FLAVORS:                          # line 44
```

This module formerly bypassed the breadth tier and read the raw legacy flavor
string. After 2D retirement, `discovery` maps to `flavor="balanced"` internally
(`planner.py:106`), so old discovery queries lost their `_DIVERSIFY_FLAVORS`
match. This was partially compensated by `_DIVERSIFY_BUDGET_REASONS =
{"balanced_synthesis", "balanced_discovery"}` (line 17), but the flavor-string
check was a design-layer violation: the authority chain says breadth (policy)
owns retrieval width, not the legacy flavor label.

**Action:** Done. `_DIVERSIFY_BREADTHS = {"broad"}` replaced the legacy
`recall` flavor check. `balanced_synthesis` and `balanced_discovery` still
diversify through explicit budget reasons.

---

### 3.3 `hyde_search.py` structural guard — defense-in-depth

| | |
|---|---|
| **Location** | `hyde_search.py` guard for `entity_mode == "multi_explicit"` (currently around lines 85-86) |
| **Status** | Keep — verified defense-in-depth for stale/manual plans |

```python
if state.get("entity_mode") == "multi_explicit":
    return {"search_mode_hyde": "disabled_multi", ...}
```

This runtime check is the `disabled_multi` guard from Design 1 §3.2. The same
semantic is expressed as `entity_scope != "multi"` in the routing decision —
and it **is**, at `routing.py:53`. `_plan_from_routing` now reads
`decision.use_hyde`, so the canonical planner path no longer needs this guard
for correctness.

The guard is still useful because `run_direct_search` trusts an existing
`query_plan` on state. A stale/manual plan with `use_hyde=true` and
`entity_mode="multi_explicit"` can still call `hyde_search_node`; the guard
keeps that edge case from running HyDE. `test_hyde_search.py` now
characterizes this path.

**Action:** Keep the guard. This is not a cleanup candidate unless
`run_direct_search` stops accepting precomputed plans or validates/canonicalizes
their `use_hyde` value before dispatch.

---

### 3.4 `intent.active_mode` runtime flag — retirement candidate

| | |
|---|---|
| **Location** | `runtime_settings.py:28` (`_DEFAULTS["intent.active_mode"] = "true"`); consumer at `planner.py:80` |
| **Design says** | 2D-A §2: *"`intent.active_mode` can be retired later, once rollback via `inline_enabled=false` is considered sufficient."* |

Both intent flags (`inline_enabled`, `active_mode`) currently default to `"true"`.
`inline_enabled` is the kill switch for classifier cost/latency failures.
`active_mode` controls whether the gated result drives `query_plan`. If the
active path has proven stable, `active_mode` can be collapsed: removing the flag
and the `emitted_bundle = gated_bundle if _intent_flag("intent.active_mode")
else det_bundle` branch at `planner.py:80`.

**Action:** Operational decision — defer until the active path has a longer
observation window, per the 2D-A recommendation.

---

## Dependency Graph for Removal

```
1.1 _decide_multi_hop ──────────────────────────────────────► done

1.4 archive compare_activation_eval.py ─────────────────────► done

1.2 delete proposal_execution ──────────────────────────────► done

replacement active-path reporting / explicit watch retirement
         └──► later archive report_inline_shadow.py ──► delete remaining shadow fields ──► delete tests

1.3 delete trust_gate() ────────────────────────────────────► done

1.5 later archive route_scoring.py / scorer only with regression-tool sign-off

2.1 fix legacy_use_hyde ──► done; 3.3 HyDE guard retained as defense-in-depth
         │
         └── (independent of all Tier-1 items)

3.1 entity_mode=multi_hop ─────────────────────────────────► done

3.4 active_mode flag ──► operational sign-off, then collapse planner branch
```

Completed cleanup: §1.1, write-only `proposal_execution` from §1.2, §2.1,
§1.3, §2.2, §2.3, §2.4, §3.1, §3.2, §3.3 verification, and the completed
`compare_activation_eval.py` gate comparator from §1.4. Deleting
`proposal_diverged` / `activatable_diverged`, archiving remaining regression
tools, and collapsing `intent.active_mode` wait for operational sign-off or
replacement reporting.

---

## Retained Operational Scaffolding

The remaining items are intentionally retained operating controls or regression
tools, not hidden routing authorities. Treat them as named scaffolding with
explicit retirement triggers.

| Item | Why it stays | Retirement trigger | Do not remove until |
|---|---|---|---|
| `intent.inline_enabled` | Hard kill switch for inline classifier cost, latency, and provider failures. `false` skips the LLM call entirely. | A different hard kill switch exists at the same operational layer. | There is an equivalent instant rollback that removes classifier calls, not only route activation. |
| `intent.active_mode` | Shadow-only mode: classifier runs and writes `inline_shadow`, but deterministic routing still drives `query_plan`. | Shadow-only live validation is no longer needed after future classifier or prompt changes. | Operational sign-off confirms `inline_enabled=false` is sufficient rollback and no dark-launch mode is required. |
| `report_inline_shadow.py` | Lightweight post-flip watch over live `query_run_stats`: classifier run rate, fallback/error slices, latency, and activatable divergences. | Replacement active-path reporting exists, or the watch is explicitly retired. | Equivalent production visibility exists for inline classifier health and route divergences. |
| `proposal_diverged` / `activatable_diverged` | Persisted trace inputs for `report_inline_shadow.py` and manual audits. They do not drive live behavior. | `report_inline_shadow.py` is archived or rewritten to use another source. | No retained script, dashboard, or audit path reads these fields. |
| `route_scoring.py` / `score_routing_golden_set.py` | Routing golden-set regression harness for positive activation correctness. This is separate from answer-quality golden sets. | The routing golden set is moved to another permanent test harness or explicitly retired. | There is another way to score expected-route accuracy and ambiguous-case safety. |
| `hyde_search.py` multi-entity guard | Defense-in-depth for stale/manual plans that set `use_hyde=true` despite `entity_mode="multi_explicit"`. | `run_direct_search` canonicalizes precomputed plans or stops accepting them. | No HyDE-reachable path can bypass `_plan_from_routing`'s `use_hyde=False` for multi-entity scope. |

This list is the expected residue of the staged rollout. New cleanup PRs should
either satisfy one of these retirement triggers or leave the item alone.

---

## Out of Scope (verified clean)

The following were investigated and confirmed **not** to be cleanup candidates:

- **`_BROAD_SIGNALS`** (`entity_confirm.py:11`) — live, feeds `entity_mode`
  into the inferred tier via state. Not duplicated.
- **`DISCOVERY_KEYWORDS` / `RESPONSIBILITY_HOP_KEYWORDS`** (`multi_hop.py:20,27`)
  — shared by `inferred.py:10` via import; still used in `run_multi_hop_search`.
- **`SYNTHESIS_QUERY_MARKERS`** (`intent_markers.py:5`) — clean single source.
- **`needs_discovery` inferred signal** — the replacement system, not a remnant.
- **`hop_plan = "discovery"`** (`multi_hop.py:118,214`) — multi-hop execution
  plan string, unrelated to breadth. Naming collision noted but not a remnant.
- **Frontend `discovery` labels/stats** — intentionally retained for historical
  row display; `SELECTABLE_FLAVOR_KEYS` already excludes it; guarded by
  `labelMaps.test.ts`.
- **`build_query_plan`** (`planner.py:92`) — active as the deterministic
  fallback inside `get_query_plan`; also a heavily-used test entry point.
- **`discovery` compat shims** (`breadth.py:16`, `planner.py:106-114`) —
  intentionally retained migration mappings for legacy input.

---

## Verification

- Audit snapshot unit suite baseline: **614 passed** (2026-06-13). Treat this
  as a historical baseline, not a fresh verification requirement; current full
  local runs may depend on Milvus availability during collection.
- Before executing any action item, re-grep the symbol and verify file/line
  locations. The audit records a snapshot and line numbers may drift as prompt
  or test code changes.
- Each Tier-1 deletion should be followed by a test run; tests referencing
  deleted symbols must be migrated or removed in the same commit.
- §2.1 fix must be verified with a direct planner unit assertion:
  `build_query_plan(..., entity_mode="multi_explicit").use_hyde is False`.
  Update the existing compatibility test that currently asserts the old
  two-value mismatch (`plan.use_hyde is True` while `decision.use_hyde is
  False`). A golden/full run is useful as follow-up, but it is not sufficient
  because `hyde_search.py` currently has a compensating runtime guard.
