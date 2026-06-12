# Retrieval Control Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the query planner's routing knobs into the four-tier control model (preference / inferred / derived / infra) with a single authority chain, **preserving all current behavior exactly**.

**Architecture:** Introduce a new `app/rag/query/control/` package of pure functions — `resolve_breadth`, `infer_signals`, `resolve_budget_profile`, `derive_routing_decision`, `build_routing_trace`. Then rewrite `planner.build_query_plan` to compute a `RoutingDecision` via those functions and map it onto the **existing** `query_plan` dict shape, so the ~9 downstream consumers and the golden set see no change. `retrieval_flavor` is renamed to `retrieval_breadth` (4 values, `discovery` retained as deprecated); `_decide_multi_hop` folds into the inferred tier so `RoutingDecision.use_multi_hop` is the single execution flag.

**Tech Stack:** Python 3.12, dataclasses, pytest. Spec: `docs/retrieval_control_model_design.md`.

**Behavior-preservation gate (whole-plan):** `test_query_planner.py` budget/flag values stay numerically identical (field names migrate `retrieval_flavor`→`retrieval_breadth`); golden-set retrieval-only Hit@5/Hit@10 and full pass rate identical. No observable delta.

---

## File Structure

**Create:**
- `backend/app/rag/query/control/__init__.py` — package marker, re-exports.
- `backend/app/rag/query/control/breadth.py` — `RetrievalBreadth`, `resolve_breadth`, `BreadthProfile`, `BREADTH_PROFILES`.
- `backend/app/rag/query/control/inferred.py` — `InferredSignals`, `infer_signals` (folds the 3 keyword sites + entity_scope).
- `backend/app/rag/query/control/budget.py` — `resolve_budget_profile` (§3.3 table) reusing `RetrievalBudget`.
- `backend/app/rag/query/control/routing.py` — `RoutingDecision`, `derive_routing_decision`, `build_routing_trace`.
- `backend/tests/unit/test_control_breadth.py`, `test_control_inferred.py`, `test_control_budget.py`, `test_control_routing.py`.

**Modify:**
- `backend/app/rag/query/planner.py` — rewrite `build_query_plan` internals to delegate to `control/`; rename `retrieval_flavor`→`retrieval_breadth` on `QueryPlan`; stash the trace.
- `backend/app/rag/query/search_pipeline.py:88-91` — `_should_run_multi_hop` reads the single `use_multi_hop` flag.
- `backend/app/services/query_observability.py:118` — read `retrieval_breadth` (back-compat fallback to `retrieval_flavor`).
- `backend/tests/unit/test_query_planner.py` — migrate field names, keep value assertions.

**Untouched (consume `query_plan` dict unchanged):** `build_prompt.py`, `search.py`, `hyde_search.py`, `rerank.py`, `diversify_context.py`, `query_expansion.py`, `rrf_fusion.py`, `direct_search.py`.

---

## Task 0: Characterization safety net

Lock current planner output before refactoring, so any drift is caught.

**Files:**
- Test: `backend/tests/unit/test_planner_characterization.py` (create)

- [ ] **Step 1: Write characterization tests pinning every current branch**

```python
"""Characterization: pins current build_query_plan output before the control-model
refactor. These values MUST stay identical through the refactor (behavior gate)."""

from app.rag.query.config import QueryConfig
from app.rag.query.planner import build_query_plan

CFG = QueryConfig(search_limit=10, rrf_max_results=20, rerank_max_top_k=10, hyde_limit=10)


def _budget(plan):
    b = plan.budget
    return (b.search_limit, b.hyde_limit, b.rrf_top_k, b.rerank_candidate_k,
            b.final_context_k, b.max_context_chars, b.per_entity_min_k)


def test_exact_single():
    p = build_query_plan("报销标准是什么？", "single", QueryConfig(retrieval_flavor="exact"))
    assert (p.use_hyde, p.use_query_expansion, p.use_multi_hop) == (False, False, False)
    assert p.fallback_policy.entity_filter_to_global is False
    assert _budget(p) == (8, 0, 8, 8, 3, 5000, 3)
    assert p.prompt_policy.template == "default"


def test_recall_single():
    p = build_query_plan("报销标准是什么？", "single", QueryConfig(retrieval_flavor="recall"))
    assert (p.use_hyde, p.use_query_expansion) == (False, True)
    assert _budget(p) == (20, 0, 40, 30, 8, 14000, 8)


def test_discovery_broad():
    p = build_query_plan("哪些公司提到了报销？", "broad", QueryConfig(retrieval_flavor="discovery"))
    assert p.use_multi_hop is True
    assert p.fallback_policy.entity_filter_to_global is False
    assert _budget(p) == (10, 0, 20, 10, 10, 8000, 5)
    assert p.prompt_policy.template == "broad"


def test_balanced_default_single():
    p = build_query_plan("报销标准是什么？", "single", CFG)
    assert (p.use_hyde, p.use_query_expansion, p.use_multi_hop) == (True, False, False)
    assert _budget(p) == (10, 10, 20, 10, 10, 8000, 5)
    assert p.prompt_policy.template == "default"


def test_balanced_broad_scope():
    p = build_query_plan("哪些公司提到了报销？", "broad", CFG)
    assert _budget(p) == (24, 10, 32, 20, 8, 12000, 5)
    assert p.prompt_policy.template == "broad"


def test_balanced_synthesis():
    p = build_query_plan("安全事件响应和运维故障响应有什么关联和区别？", "single", CFG)
    assert _budget(p) == (20, 10, 32, 20, 10, 10000, 5)


def test_balanced_multi_explicit_per_entity():
    p = build_query_plan("A公司和B公司的报销标准", "multi_explicit", CFG)
    assert p.budget.per_entity_min_k == 8
    assert p.prompt_policy.template == "multi_entity"
```

- [ ] **Step 2: Run to verify they pass against current code**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_planner_characterization.py -v`
Expected: PASS (all 7). If any fail, fix the expected value to match current behavior before proceeding — this file is the ground truth.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_planner_characterization.py
git commit -m "test: characterization net for query planner before control-model refactor"
```

---

## Task 1: `breadth.py` — retrieval_breadth + profiles

**Files:**
- Create: `backend/app/rag/query/control/__init__.py`, `backend/app/rag/query/control/breadth.py`
- Test: `backend/tests/unit/test_control_breadth.py`

- [ ] **Step 1: Write the failing test**

```python
from app.rag.query.control.breadth import (
    BREADTH_PROFILES, resolve_breadth, VALID_BREADTHS,
)


def test_resolve_renames_legacy_flavors_1to1():
    assert resolve_breadth("exact") == "precise"
    assert resolve_breadth("balanced") == "balanced"
    assert resolve_breadth("recall") == "broad"
    assert resolve_breadth("discovery") == "discovery"


def test_resolve_passthrough_and_default():
    assert resolve_breadth("precise") == "precise"      # already migrated
    assert resolve_breadth("nonsense") == "balanced"    # default, like _normalize_flavor


def test_profiles_match_design_3_2():
    assert VALID_BREADTHS == {"precise", "balanced", "broad", "discovery"}
    p = BREADTH_PROFILES
    assert (p["precise"].sets_hyde, p["precise"].sets_expansion,
            p["precise"].allows_fallback, p["precise"].permits_multi_hop) == (False, False, False, False)
    assert (p["balanced"].sets_hyde, p["balanced"].sets_expansion,
            p["balanced"].allows_fallback, p["balanced"].permits_multi_hop) == (True, False, True, True)
    assert (p["broad"].sets_hyde, p["broad"].sets_expansion,
            p["broad"].allows_fallback, p["broad"].permits_multi_hop) == (False, True, True, True)
    assert (p["discovery"].sets_hyde, p["discovery"].sets_expansion,
            p["discovery"].allows_fallback, p["discovery"].permits_multi_hop) == (False, False, False, True)
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_control_breadth.py -v`
Expected: FAIL — `ModuleNotFoundError: app.rag.query.control.breadth`

- [ ] **Step 3: Implement**

Create `backend/app/rag/query/control/__init__.py`:

```python
"""Retrieval control model (Design 1) — preference / inferred / derived tiers."""
```

Create `backend/app/rag/query/control/breadth.py`:

```python
"""Retrieval breadth — the user-policy tier (renamed from retrieval_flavor).

precise | balanced | broad are clean precision↔recall values; discovery is a
deprecated transitional value retained verbatim (design §2). See design §3.2 for
the breadth profile table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RetrievalBreadth = Literal["precise", "balanced", "broad", "discovery"]

VALID_BREADTHS = {"precise", "balanced", "broad", "discovery"}

# 1:1 rename of legacy retrieval_flavor values (design §7/§8).
_FLAVOR_TO_BREADTH = {
    "exact": "precise",
    "balanced": "balanced",
    "recall": "broad",
    "discovery": "discovery",
}


def resolve_breadth(flavor: str) -> RetrievalBreadth:
    """Map a legacy retrieval_flavor (or already-migrated breadth) to a breadth.

    Unknown values default to balanced, matching the old _normalize_flavor.
    """
    if flavor in VALID_BREADTHS:
        return flavor  # type: ignore[return-value]
    return _FLAVOR_TO_BREADTH.get(flavor, "balanced")  # type: ignore[return-value]


@dataclass(frozen=True)
class BreadthProfile:
    sets_hyde: bool          # breadth wants HyDE (gated by enable_hyde)
    sets_expansion: bool     # breadth wants query expansion (gated by enable_query_expansion)
    allows_fallback: bool    # breadth permits entity→global fallback (also gated by strict_evidence)
    permits_multi_hop: bool  # breadth permits multi-hop (veto-only; never forces)


# Grounded in current planner.py branches (design §3.2). discovery additionally
# bypasses enable_multi_hop — that impurity lives in routing.py, not here.
BREADTH_PROFILES: dict[str, BreadthProfile] = {
    "precise":   BreadthProfile(False, False, False, False),
    "balanced":  BreadthProfile(True,  False, True,  True),
    "broad":     BreadthProfile(False, True,  True,  True),
    "discovery": BreadthProfile(False, False, False, True),
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_control_breadth.py -v`
Expected: PASS (3)

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/query/control/__init__.py backend/app/rag/query/control/breadth.py backend/tests/unit/test_control_breadth.py
git commit -m "feat: add retrieval_breadth resolution and breadth profiles"
```

---

## Task 2: `inferred.py` — fold the three keyword sites

Consolidates `intent_markers.SYNTHESIS_QUERY_MARKERS`, `multi_hop.DISCOVERY_KEYWORDS`/`RESPONSIBILITY_HOP_KEYWORDS`, and `entity_confirm._BROAD_SIGNALS` (via `entity_mode`) into one inferred-signal function. `needs_multi_hop` **is** today's `_decide_multi_hop` logic (design §3.1). `requested_format` is always `None` in Design 1; `confidence` is always `"high"`.

**Files:**
- Create: `backend/app/rag/query/control/inferred.py`
- Test: `backend/tests/unit/test_control_inferred.py`

- [ ] **Step 1: Write the failing test**

```python
from app.rag.query.control.inferred import InferredSignals, infer_signals


def test_entity_scope_maps_from_entity_mode():
    assert infer_signals("q", "single", []).entity_scope == "single"
    assert infer_signals("q", "multi_explicit", []).entity_scope == "multi"
    assert infer_signals("q", "broad", []).entity_scope == "broad"
    assert infer_signals("q", "none", []).entity_scope == "none"


def test_needs_synthesis_from_markers():
    assert infer_signals("A和B有什么区别？", "single", []).needs_synthesis is True
    assert infer_signals("报销标准是什么？", "single", []).needs_synthesis is False


def test_needs_multi_hop_folds_decide_multi_hop():
    # discovery keyword + broad/none scope → True
    assert infer_signals("哪些公司提到了报销？", "broad", []).needs_multi_hop is True
    assert infer_signals("谁负责报销审批？", "none", []).needs_multi_hop is True
    # keyword but single/multi scope → False (scope gate)
    assert infer_signals("哪些公司提到了报销？", "single", []).needs_multi_hop is False
    # no keyword → False
    assert infer_signals("报销标准是什么？", "none", []).needs_multi_hop is False


def test_d1_invariants():
    sig = infer_signals("哪些公司提到了报销？", "broad", [])
    assert sig.needs_discovery is True
    assert sig.requested_format is None   # D1 never extracts format
    assert sig.confidence == "high"       # D1 deterministic = trusted
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_control_inferred.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Create `backend/app/rag/query/control/inferred.py`:

```python
"""Inferred tier (Design 1, deterministic) — one place for the query-type signals.

Folds the three current keyword sites:
  - intent_markers.SYNTHESIS_QUERY_MARKERS        → needs_synthesis
  - multi_hop.DISCOVERY_KEYWORDS / RESPONSIBILITY  → needs_discovery / needs_multi_hop
  - entity_confirm._BROAD_SIGNALS (via entity_mode) → entity_scope

needs_multi_hop reproduces _decide_multi_hop (design §3.1): it IS the scope+keyword
gate, so RoutingDecision.use_multi_hop becomes the single execution flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.rag.query.intent_markers import has_synthesis_marker
from app.rag.query.multi_hop import DISCOVERY_KEYWORDS, RESPONSIBILITY_HOP_KEYWORDS

EntityScope = Literal["single", "multi", "broad", "none"]

_ENTITY_MODE_TO_SCOPE: dict[str, EntityScope] = {
    "single": "single",
    "multi_explicit": "multi",
    "broad": "broad",
    "none": "none",
}

_DISCOVERY_GATE_KEYWORDS = DISCOVERY_KEYWORDS + RESPONSIBILITY_HOP_KEYWORDS


@dataclass(frozen=True)
class InferredSignals:
    entity_scope: EntityScope
    needs_synthesis: bool
    needs_discovery: bool
    needs_multi_hop: bool
    requested_format: str | None = None     # Design 2 only; always None in D1
    confidence: str = "high"                 # D1 deterministic = trusted
    reasons: list[str] = field(default_factory=list)


def infer_signals(query: str, entity_mode: str, matched_entities: list[str]) -> InferredSignals:
    scope = _ENTITY_MODE_TO_SCOPE.get(entity_mode, "none")
    needs_synthesis = has_synthesis_marker(query)
    has_discovery_kw = any(kw in query for kw in _DISCOVERY_GATE_KEYWORDS)
    # _decide_multi_hop folded in: scope gate (broad/none) AND keyword gate.
    needs_multi_hop = scope in ("broad", "none") and has_discovery_kw

    reasons: list[str] = []
    if needs_synthesis:
        reasons.append("synthesis:marker")
    if needs_multi_hop:
        reasons.append("multi_hop:discovery_keyword")

    return InferredSignals(
        entity_scope=scope,
        needs_synthesis=needs_synthesis,
        needs_discovery=has_discovery_kw,
        needs_multi_hop=needs_multi_hop,
        requested_format=None,
        confidence="high",
        reasons=reasons,
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_control_inferred.py -v`
Expected: PASS (4)

Cross-check the fold is faithful: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_multi_hop.py -q` (still passes — we did not touch `_decide_multi_hop`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/query/control/inferred.py backend/tests/unit/test_control_inferred.py
git commit -m "feat: add deterministic inferred-signal module folding keyword sites"
```

---

## Task 3: `budget.py` — the §3.3 budget profile table

Reproduces every current `planner.py` budget branch exactly, reusing `RetrievalBudget`. Keep the existing `reason` strings so consumers/observability are unchanged.

**Files:**
- Create: `backend/app/rag/query/control/budget.py`
- Test: `backend/tests/unit/test_control_budget.py`

- [ ] **Step 1: Write the failing test**

```python
from app.rag.query.config import QueryConfig
from app.rag.query.control.budget import resolve_budget_profile

CFG = QueryConfig(search_limit=10, rrf_max_results=20, rerank_max_top_k=10, hyde_limit=10)


def _t(b):
    return (b.search_limit, b.hyde_limit, b.rrf_top_k, b.rerank_candidate_k,
            b.final_context_k, b.max_context_chars, b.per_entity_min_k)


def test_precise():
    assert _t(resolve_budget_profile("precise", "single", False, CFG)) == (8, 0, 8, 8, 3, 5000, 3)


def test_broad():
    assert _t(resolve_budget_profile("broad", "single", False, CFG)) == (20, 0, 40, 30, 8, 14000, 8)


def test_discovery():
    assert _t(resolve_budget_profile("discovery", "broad", False, CFG)) == (10, 0, 20, 10, 10, 8000, 5)


def test_balanced_default():
    assert _t(resolve_budget_profile("balanced", "single", False, CFG)) == (10, 10, 20, 10, 10, 8000, 5)


def test_balanced_broad_scope():
    assert _t(resolve_budget_profile("balanced", "broad", False, CFG)) == (24, 10, 32, 20, 8, 12000, 5)


def test_balanced_synthesis():
    assert _t(resolve_budget_profile("balanced", "single", True, CFG)) == (20, 10, 32, 20, 10, 10000, 5)


def test_multi_scope_modifier_sets_per_entity_8():
    assert resolve_budget_profile("balanced", "multi", False, CFG).per_entity_min_k == 8
    assert resolve_budget_profile("precise", "multi", False, CFG).per_entity_min_k == 8


def test_reason_strings_preserved():
    assert resolve_budget_profile("precise", "single", False, CFG).reason == "exact_precision"
    assert resolve_budget_profile("balanced", "single", True, CFG).reason == "balanced_synthesis"
    assert resolve_budget_profile("balanced", "broad", False, CFG).reason == "balanced_broad"
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_control_budget.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Create `backend/app/rag/query/control/budget.py`:

```python
"""Budget profile table (design §3.3) — explicit per-(breadth, scope, synthesis)
limit sets reproducing each current planner.py branch. Reuses RetrievalBudget and
the existing _clamp_budget so consumers and reason strings are unchanged."""

from __future__ import annotations

import dataclasses

from app.rag.query.config import QueryConfig
from app.rag.query.planner import RetrievalBudget, _clamp_budget


def resolve_budget_profile(
    breadth: str, entity_scope: str, needs_synthesis: bool, cfg: QueryConfig,
) -> RetrievalBudget:
    if breadth == "precise":
        budget = RetrievalBudget(
            search_limit=8, hyde_limit=0, rrf_top_k=8, rerank_candidate_k=8,
            final_context_k=3, max_context_chars=5000, per_entity_min_k=3,
            reason="exact_precision",
        )
    elif breadth == "broad":
        budget = RetrievalBudget(
            search_limit=20, hyde_limit=0, rrf_top_k=40, rerank_candidate_k=30,
            final_context_k=8, max_context_chars=14000, per_entity_min_k=8,
            reason="recall_high_coverage",
        )
    elif breadth == "discovery":
        budget = RetrievalBudget(
            search_limit=cfg.search_limit, hyde_limit=0, rrf_top_k=cfg.rrf_max_results,
            rerank_candidate_k=cfg.rerank_max_top_k, final_context_k=cfg.rerank_max_top_k,
            max_context_chars=8000, per_entity_min_k=5, reason="discovery_current_path",
        )
    elif entity_scope == "broad":
        budget = RetrievalBudget(
            search_limit=min(cfg.search_limit * 2, 24), hyde_limit=cfg.hyde_limit,
            rrf_top_k=min(cfg.rrf_max_results * 2, 32),
            rerank_candidate_k=min(cfg.rerank_max_top_k * 2, 24),
            final_context_k=min(cfg.rerank_max_top_k * 2, 8),
            max_context_chars=12000, per_entity_min_k=5, reason="balanced_broad",
        )
    elif needs_synthesis:
        budget = RetrievalBudget(
            search_limit=min(max(cfg.search_limit * 2, 20), 24), hyde_limit=cfg.hyde_limit,
            rrf_top_k=min(max(cfg.rrf_max_results * 2, 32), 32),
            rerank_candidate_k=min(max(cfg.rerank_max_top_k * 2, 20), 24),
            final_context_k=cfg.rerank_max_top_k, max_context_chars=10000,
            per_entity_min_k=5, reason="balanced_synthesis",
        )
    else:
        budget = RetrievalBudget(
            search_limit=cfg.search_limit, hyde_limit=cfg.hyde_limit,
            rrf_top_k=cfg.rrf_max_results, rerank_candidate_k=cfg.rerank_max_top_k,
            final_context_k=cfg.rerank_max_top_k, max_context_chars=8000,
            per_entity_min_k=5, reason="balanced_current_defaults",
        )

    # §3.5 structural modifier: multi-entity sets the per-entity coverage floor.
    if entity_scope == "multi":
        budget = dataclasses.replace(budget, per_entity_min_k=8)
    return _clamp_budget(budget)
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_control_budget.py -v`
Expected: PASS (8)

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/query/control/budget.py backend/tests/unit/test_control_budget.py
git commit -m "feat: add budget profile table reproducing current planner branches"
```

---

## Task 4: `routing.py` — RoutingDecision + authority chain + trace

The derived tier. Applies the authority chain (§3), the entity_scope structural constraints (§3.5), the prompt precedence (§3.4), and the discovery `enable_multi_hop` bypass (§3.2). Emits the three-section trace (§6).

**Files:**
- Create: `backend/app/rag/query/control/routing.py`
- Test: `backend/tests/unit/test_control_routing.py`

- [ ] **Step 1: Write the failing test**

```python
from app.rag.query.config import QueryConfig
from app.rag.query.control.inferred import infer_signals
from app.rag.query.control.routing import derive_routing_decision, build_routing_trace

CFG = QueryConfig(search_limit=10, rrf_max_results=20, rerank_max_top_k=10, hyde_limit=10)


def _decide(query, entity_mode, breadth, cfg=CFG):
    return derive_routing_decision(infer_signals(query, entity_mode, []), breadth, cfg)


def test_precise_suppresses_multi_hop_and_fallback():
    d = _decide("哪些公司提到了报销？", "broad", "precise")
    assert d.use_multi_hop is False                # precise vetoes
    assert d.use_entity_fallback is False
    assert "precise breadth suppresses multi-hop" in " ".join(d.vetoes)


def test_broad_does_not_invent_multi_hop():
    d = _decide("报销标准是什么？", "none", "broad")   # no discovery keyword
    assert d.use_multi_hop is False


def test_infra_veto_disables_multi_hop_for_non_discovery():
    cfg = QueryConfig(use_multi_hop=False)
    d = _decide("哪些公司提到了报销？", "broad", "balanced", cfg)
    assert d.use_multi_hop is False                # enable_multi_hop veto


def test_discovery_bypasses_enable_multi_hop():
    cfg = QueryConfig(use_multi_hop=False)
    d = _decide("哪些公司提到了报销？", "broad", "discovery", cfg)
    assert d.use_multi_hop is True                 # documented deprecated impurity


def test_entity_fallback_only_single():
    assert _decide("报销标准", "single", "balanced").use_entity_fallback is True
    assert _decide("报销标准", "multi_explicit", "balanced").use_entity_fallback is False
    assert _decide("报销标准", "broad", "balanced").use_entity_fallback is False


def test_strict_evidence_suppresses_fallback():
    cfg = QueryConfig(strict_evidence=True)
    assert _decide("报销标准", "single", "balanced", cfg).use_entity_fallback is False


def test_prompt_variant_precedence():
    assert _decide("A和B的区别", "multi_explicit", "discovery").prompt_variant == "multi_entity"
    assert _decide("哪些公司", "broad", "discovery").prompt_variant == "broad"
    assert _decide("哪些公司", "broad", "balanced").prompt_variant == "broad"   # entity_scope=broad
    assert _decide("报销标准", "single", "balanced").prompt_variant == "default"


def test_hyde_expansion_breadth_owned():
    assert _decide("报销标准", "single", "balanced").use_hyde is True
    assert _decide("报销标准", "single", "broad").use_hyde is False
    assert _decide("报销标准", "single", "broad").use_query_expansion is True


def test_trace_has_three_sections():
    sig = infer_signals("哪些公司提到了报销？", "broad", [])
    d = derive_routing_decision(sig, "precise", CFG)
    trace = build_routing_trace(sig, "precise", CFG, d)
    assert set(trace) == {"intent", "policy", "infra", "routing_decision"}
    assert trace["policy"]["retrieval_breadth"] == "precise"
    assert trace["routing_decision"]["use_multi_hop"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_control_routing.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Create `backend/app/rag/query/control/routing.py`:

```python
"""Derived tier (design §3-§6): RoutingDecision via the authority chain.

effective = requested (intent) ∧ permitted (breadth) ∧ available (infra), with the
entity_scope structural constraints (§3.5), prompt precedence (§3.4), and the
deprecated discovery enable_multi_hop bypass (§3.2)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.rag.query.config import QueryConfig
from app.rag.query.control.breadth import BREADTH_PROFILES, RetrievalBreadth
from app.rag.query.control.budget import resolve_budget_profile
from app.rag.query.control.inferred import InferredSignals


@dataclass(frozen=True)
class RoutingDecision:
    use_hyde: bool
    use_query_expansion: bool
    use_multi_hop: bool
    use_entity_fallback: bool
    budget_reason: str
    prompt_variant: str           # multi_entity | broad | default
    answer_shape: str             # bullets_or_table | prose (D1: from needs_synthesis)
    steps: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    vetoes: list[str] = field(default_factory=list)


def _prompt_variant(entity_scope: str, breadth: str) -> str:
    # Reproduces _prompt_template precedence (design §3.4): multi wins first.
    if entity_scope == "multi":
        return "multi_entity"
    if breadth == "discovery" or entity_scope == "broad":
        return "broad"
    return "default"


def derive_routing_decision(
    inferred: InferredSignals, breadth: RetrievalBreadth, cfg: QueryConfig,
) -> RoutingDecision:
    profile = BREADTH_PROFILES[breadth]
    scope = inferred.entity_scope
    vetoes: list[str] = []
    reasons: list[str] = list(inferred.reasons)

    # Breadth-owned strategy (§3.2). HyDE's entity_scope != multi structural guard
    # is realized at runtime in hyde_search.py (disabled_multi) and asserted there;
    # use_hyde here stays breadth-owned to preserve the existing search_mode_hyde label.
    use_hyde = profile.sets_hyde and cfg.use_hyde
    use_query_expansion = profile.sets_expansion and cfg.use_query_expansion

    # Entity→global fallback (§3.2, §3.5): single-scope only, breadth + strict both suppress.
    use_entity_fallback = (
        scope == "single" and profile.allows_fallback and not cfg.strict_evidence
    )

    # Multi-hop (§3.1): single execution flag. needs_multi_hop already folds _decide_multi_hop.
    permitted = profile.permits_multi_hop
    if breadth == "discovery":
        available = True  # deprecated impurity: bypasses enable_multi_hop (§3.2)
    else:
        available = cfg.use_multi_hop
    use_multi_hop = inferred.needs_multi_hop and permitted and available

    if inferred.needs_multi_hop and not permitted:
        vetoes.append(f"{breadth} breadth suppresses multi-hop")
    if inferred.needs_multi_hop and permitted and not available and breadth != "discovery":
        vetoes.append("enable_multi_hop infra veto on multi-hop")

    if not (scope == "single") and profile.allows_fallback and not cfg.strict_evidence:
        # fallback inapplicable for multi/broad/none (no entity filter) — informational
        pass

    budget = resolve_budget_profile(breadth, scope, inferred.needs_synthesis, cfg)
    prompt_variant = _prompt_variant(scope, breadth)
    answer_shape = "bullets_or_table" if inferred.needs_synthesis else "prose"

    steps: list[str] = []
    if scope == "multi":
        steps.append("multi_entity")
    if use_multi_hop:
        steps.append("multi_hop")

    return RoutingDecision(
        use_hyde=use_hyde,
        use_query_expansion=use_query_expansion,
        use_multi_hop=use_multi_hop,
        use_entity_fallback=use_entity_fallback,
        budget_reason=budget.reason,
        prompt_variant=prompt_variant,
        answer_shape=answer_shape,
        steps=steps,
        reasons=reasons,
        vetoes=vetoes,
    )


def build_routing_trace(
    inferred: InferredSignals, breadth: RetrievalBreadth, cfg: QueryConfig,
    decision: RoutingDecision,
) -> dict:
    """Three-section trace (design §6): intent / policy / infra → routing_decision."""
    return {
        "intent": {
            "entity_scope": inferred.entity_scope,
            "needs_synthesis": inferred.needs_synthesis,
            "needs_discovery": inferred.needs_discovery,
            "needs_multi_hop": inferred.needs_multi_hop,
            "confidence": inferred.confidence,
            "reasons": inferred.reasons,
        },
        "policy": {
            "retrieval_breadth": breadth,
            "strict_evidence": bool(cfg.strict_evidence),
            "vetoes": decision.vetoes,
        },
        "infra": {
            "enable_hyde": bool(cfg.use_hyde),
            "enable_query_expansion": bool(cfg.use_query_expansion),
            "enable_multi_hop": bool(cfg.use_multi_hop),
        },
        "routing_decision": {
            "use_hyde": decision.use_hyde,
            "use_query_expansion": decision.use_query_expansion,
            "use_multi_hop": decision.use_multi_hop,
            "use_entity_fallback": decision.use_entity_fallback,
            "budget_reason": decision.budget_reason,
            "prompt_variant": decision.prompt_variant,
            "answer_shape": decision.answer_shape,
            "steps": decision.steps,
            "reasons": decision.reasons,
        },
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_control_routing.py -v`
Expected: PASS (9)

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/query/control/routing.py backend/tests/unit/test_control_routing.py
git commit -m "feat: add RoutingDecision authority chain and three-section trace"
```

---

## Task 5: Integrate into `planner.build_query_plan` (behavior-preserving)

Rewrite the planner internals to delegate to `control/`, mapping `RoutingDecision` onto the existing `QueryPlan`/`query_plan` dict so consumers are unchanged. Rename `retrieval_flavor`→`retrieval_breadth` on `QueryPlan`. Stash the trace under a new key.

**Files:**
- Modify: `backend/app/rag/query/planner.py`
- Test: `backend/tests/unit/test_planner_characterization.py` (must still pass), `backend/tests/unit/test_query_planner.py` (migrate)

- [ ] **Step 1: Rewrite `build_query_plan` and `query_plan_node`**

In `backend/app/rag/query/planner.py`, replace the body of `build_query_plan` (lines ~71-181) and `query_plan_node` (lines ~60-68). Keep `QueryPlan`, `RetrievalBudget`, `FallbackPolicy`, `PromptPolicy`, `_clamp_budget`, `get_query_plan`, `plan_budget`, `plan_allows_entity_fallback` intact. Change `QueryPlan.retrieval_flavor: RetrievalFlavor` to `retrieval_breadth: str`. New bodies:

```python
def query_plan_node(state: QueryState, config: RunnableConfig) -> dict:
    """Resolve high-level query controls into one plan for downstream nodes."""
    from app.rag.query.control.breadth import resolve_breadth
    from app.rag.query.control.inferred import infer_signals
    from app.rag.query.control.routing import build_routing_trace, derive_routing_decision

    cfg = get_query_config(config)
    query = require_query(state)
    entity_mode = state.get("entity_mode", "none")
    breadth = resolve_breadth(cfg.retrieval_flavor)
    inferred = infer_signals(query, entity_mode, list(state.get("matched_entities", [])))
    decision = derive_routing_decision(inferred, breadth, cfg)
    plan = build_query_plan(query=query, entity_mode=entity_mode, cfg=cfg)
    return {
        "query_plan": asdict(plan),
        "routing_trace": build_routing_trace(inferred, breadth, cfg, decision),
    }


def build_query_plan(query: str, entity_mode: str, cfg: QueryConfig) -> QueryPlan:
    from app.rag.query.control.breadth import resolve_breadth
    from app.rag.query.control.budget import resolve_budget_profile
    from app.rag.query.control.inferred import infer_signals
    from app.rag.query.control.routing import derive_routing_decision

    breadth = resolve_breadth(cfg.retrieval_flavor)
    inferred = infer_signals(query, entity_mode, [])
    decision = derive_routing_decision(inferred, breadth, cfg)
    budget = resolve_budget_profile(breadth, inferred.entity_scope, inferred.needs_synthesis, cfg)

    fallback_policy = FallbackPolicy(
        entity_filter_to_global=decision.use_entity_fallback or _breadth_allows_fallback(breadth, cfg),
        reason="enabled_by_breadth" if _breadth_allows_fallback(breadth, cfg) else "disabled_by_breadth_or_strict_evidence",
    )
    prompt_policy = PromptPolicy(
        strict_evidence=bool(cfg.strict_evidence),
        template=decision.prompt_variant,
    )
    return QueryPlan(
        retrieval_breadth=breadth,
        strict_evidence=bool(cfg.strict_evidence),
        use_hyde=decision.use_hyde,
        use_query_expansion=decision.use_query_expansion,
        use_multi_hop=decision.use_multi_hop,
        fallback_policy=fallback_policy,
        budget=budget,
        prompt_policy=prompt_policy,
    )
```

> **Note on `fallback_policy.entity_filter_to_global`:** today this is breadth-level (not scope-gated) — `plan_allows_entity_fallback` is read by `search.py`/`hyde_search.py` which already apply the scope/score gating downstream. To preserve behavior, `entity_filter_to_global` must equal the OLD `fallback_allowed` (breadth allows ∧ not strict), **independent of entity_scope** (the single-scope gate lives in `derive_routing_decision.use_entity_fallback`, used by the trace, not by this legacy flag). Add the helper:

```python
def _breadth_allows_fallback(breadth: str, cfg: QueryConfig) -> bool:
    from app.rag.query.control.breadth import BREADTH_PROFILES
    return BREADTH_PROFILES[breadth].allows_fallback and not cfg.strict_evidence
```

And simplify `fallback_policy` to use it directly:

```python
    allows = _breadth_allows_fallback(breadth, cfg)
    fallback_policy = FallbackPolicy(
        entity_filter_to_global=allows,
        reason="enabled_by_breadth" if allows else "disabled_by_breadth_or_strict_evidence",
    )
```

Delete the now-dead `_needs_synthesis_budget`, `_prompt_template`, `_normalize_flavor`, `VALID_FLAVORS`, `RetrievalFlavor` from `planner.py` (moved into `control/`). Update `state.py` `query_plan` consumers? None — `query_plan` dict keys unchanged except `retrieval_flavor`→`retrieval_breadth`.

- [ ] **Step 2: Run the characterization net + control tests**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_planner_characterization.py backend/tests/unit/test_control_routing.py -v`
Expected: PASS. If a characterization value differs, the mapping is wrong — fix `control/` to match, do not edit the characterization expectation.

- [ ] **Step 3: Migrate `test_query_planner.py`**

Replace every `plan.retrieval_flavor` with `plan.retrieval_breadth` and update expected values to breadth names (`"balanced"`→`"balanced"`, exact→`"precise"`, etc.). Keep all budget/flag numeric assertions unchanged. Update imports (drop `_normalize_flavor`, `_clamp_budget` stays).

- [ ] **Step 4: Run the planner test suite**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_query_planner.py -v`
Expected: PASS (all, with migrated field names)

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/query/planner.py backend/tests/unit/test_query_planner.py
git commit -m "refactor: planner delegates to control model, renames flavor->breadth"
```

---

## Task 6: Single multi-hop execution gate

Now that `RoutingDecision.use_multi_hop` (in `query_plan["use_multi_hop"]`) folds `_decide_multi_hop`, remove the second gate so the pipeline reads one flag (design §3.1).

**Files:**
- Modify: `backend/app/rag/query/search_pipeline.py:88-91`
- Test: `backend/tests/unit/test_search_pipeline.py`

- [ ] **Step 1: Write/extend the failing test**

```python
def test_should_run_multi_hop_reads_single_flag():
    from app.rag.query.search_pipeline import _should_run_multi_hop
    # plan flag True → run; no re-check of _decide_multi_hop
    assert _should_run_multi_hop({"entity_mode": "single"}, "哪些公司", {"use_multi_hop": True}) is True
    assert _should_run_multi_hop({"entity_mode": "broad"}, "报销标准", {"use_multi_hop": False}) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_search_pipeline.py::test_should_run_multi_hop_reads_single_flag -v`
Expected: FAIL (current impl ANDs `_decide_multi_hop`, returns False for the first case)

- [ ] **Step 3: Simplify the gate**

In `backend/app/rag/query/search_pipeline.py`, replace `_should_run_multi_hop`:

```python
def _should_run_multi_hop(state: QueryState, query: str, plan: dict) -> bool:
    # use_multi_hop already folds _decide_multi_hop (design §3.1); single flag.
    return bool(plan.get("use_multi_hop"))
```

- [ ] **Step 4: Run pipeline + multi_hop tests**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_search_pipeline.py backend/tests/unit/test_multi_hop.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/query/search_pipeline.py backend/tests/unit/test_search_pipeline.py
git commit -m "refactor: multi-hop reads single use_multi_hop flag (folded gate)"
```

---

## Task 7: Observability reads `retrieval_breadth`

**Files:**
- Modify: `backend/app/services/query_observability.py:118`
- Test: `backend/tests/unit/test_query_stats.py`

- [ ] **Step 1: Extend the failing test**

```python
def test_resolved_settings_reads_breadth():
    from app.services.query_observability import build_query_observability_payload
    state = {"query_plan": {"retrieval_breadth": "precise", "budget": {}, "fallback_policy": {}}}
    payload = build_query_observability_payload(state=state)
    assert payload["retrieval_flavor"] == "precise"  # key name kept for stat back-compat
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_query_stats.py::test_resolved_settings_reads_breadth -v`
Expected: FAIL (reads `retrieval_flavor` from plan, which is now `retrieval_breadth`)

- [ ] **Step 3: Update the read**

In `backend/app/services/query_observability.py`, in `_resolved_settings`, change the flavor line to prefer `retrieval_breadth` with back-compat:

```python
    flavor = str(
        plan.get("retrieval_breadth")
        or plan.get("retrieval_flavor")
        or cfg.get("retrieval_flavor")
        or "balanced"
    )
```

- [ ] **Step 4: Run observability tests**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_query_stats.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/query_observability.py backend/tests/unit/test_query_stats.py
git commit -m "refactor: observability reads retrieval_breadth with back-compat"
```

---

## Task 8: Full behavior-preservation verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend unit suite**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit -q`
Expected: PASS (no regressions). Pay attention to `test_build_prompt.py`, `test_entity_routing.py`, `test_hyde_search.py`, `test_eval_golden_set_config.py`.

- [ ] **Step 2: Golden-set retrieval-only (behavior gate)**

Run (with the stack up):
```bash
docker compose exec -T backend sh -lc 'PYTHONPATH=/app python scripts/eval_golden_set.py --golden-set /app/data/challenge_golden_set_v1.jsonl --api-base http://127.0.0.1:8010/api --mode retrieval_only --concurrency 2 --delay 0 --case-timeout 240 --output /app/data/control_model_retrieval_only.jsonl'
```
Expected: Hit@5 / Hit@10 identical to the pre-refactor baseline. Diff against the last `*_retrieval_only_results.jsonl`. Any drift = a mapping bug; fix `control/` to match.

- [ ] **Step 3: Golden-set full (behavior gate)**

Run:
```bash
docker compose exec -T backend sh -lc 'PYTHONPATH=/app python scripts/eval_golden_set.py --golden-set /app/data/challenge_golden_set_v1.jsonl --api-base http://127.0.0.1:8010/api --mode full --judge --concurrency 2 --delay 0 --case-timeout 300 --output /app/data/control_model_full_judge.jsonl'
```
Expected: full pass rate within tolerance of baseline; the discovery golden cases unchanged.

- [ ] **Step 4: Commit verification artifacts (optional)**

```bash
git add -A && git commit -m "test: control-model behavior-preservation golden-set runs" || true
```

---

## Self-Review (completed by plan author)

**Spec coverage:** resolve_breadth (§4/§8 → Task 1) · breadth profiles incl. discovery (§3.2 → Task 1) · inferred signals folding 3 keyword sites + needs_multi_hop=`_decide_multi_hop` (§3.1 → Task 2) · budget profile table + multi modifier (§3.3, §3.5 → Task 3) · authority chain, fallback single-scope, discovery bypass, prompt precedence, answer_shape, steps, vetoes (§3.1-§3.5 → Task 4) · three-section trace (§6 → Task 4) · single execution gate (§3.1 → Task 6) · observability rename (§6 → Task 7) · zero-delta gate (§7 → Tasks 0, 8). `requested_format` always null, no LLM, no `legacy_flavor_origin` — all honored (§9 non-goals).

**Deliberate behavior-preserving choices flagged for the implementer:**
1. **HyDE `entity_scope != multi`** (§3.2/§3.5) is realized by the *existing* runtime guard in `hyde_search.py` (`disabled_multi`), not duplicated in `RoutingDecision.use_hyde`, to preserve the `search_mode_hyde` label exactly. Task 4 keeps `use_hyde` breadth-owned; add an assertion in `test_hyde_search.py` that multi-entity still skips HyDE.
2. **`fallback_policy.entity_filter_to_global`** stays breadth-level (not scope-gated) because the downstream scope/score gate is unchanged; the single-scope rule lives in `use_entity_fallback` (trace only). This keeps `search.py`/`hyde_search.py` untouched.

**Open confirmation for first task:** verify `.venv` path and that `data/challenge_golden_set_v1.jsonl` baseline result files exist to diff against; if not, capture a baseline on `master` before starting Task 1.
