# Design 2A — Deterministic Intent + Shadow Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a graded deterministic confidence ladder, intent provenance, and a shadow-only trust gate that records "what the new router would have done" — with **zero active behavior change**.

**Architecture:** Extend the shipped `InferredSignals` (graded `confidence` + `source`/`fallback_used`); add a pure `trust_gate`; enrich the existing `routing_trace` with a `shadow_routing` section computed at the existing `query_plan_node` seam. No new graph node. The emitted `query_plan` is byte-for-byte Design 1 because `confidence` and the shadow record are trace-only.

**Tech Stack:** Python 3.12, dataclasses, pytest. Spec: `docs/designs/query_intent_2a_design.md`.

**Invariant (asserted by tests):** emitted `query_plan` unchanged; `shadow_routing.diverged == false` across the deterministic corpus (measured, not assumed); a forced mismatch is recorded, not acted on.

---

## File Structure

**Modify:**
- `backend/app/rag/query/control/inferred.py` — add graded `confidence` (`_confidence` helper) + `source`/`fallback_used` fields to `InferredSignals`.
- `backend/app/rag/query/control/routing.py` — add `trust_gate`; extend `build_routing_trace` with intent provenance + a `shadow_routing` section.
- `backend/app/rag/query/planner.py:60-73` — `query_plan_node` computes the would-be decision via `trust_gate` and passes it to `build_routing_trace`.
- `backend/tests/unit/test_control_inferred.py`, `test_control_routing.py` — new tests; one existing assertion check.

**Untouched (proves zero active delta):** `_resolve_routing`, `_plan_from_routing`, `derive_routing_decision`, `resolve_budget_profile`, every `query_plan` consumer, `query_observability` (already persists `routing_trace`).

---

## Task 1: Graded confidence ladder + provenance on `InferredSignals`

`confidence` becomes graded (currently constant `"high"`); add `source`/`fallback_used`. All three are trace-only — `derive_routing_decision` and `query_plan` never read them, so active routing is unchanged.

**Files:**
- Modify: `backend/app/rag/query/control/inferred.py`
- Test: `backend/tests/unit/test_control_inferred.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_control_inferred.py`:

```python
def test_confidence_ladder_v1():
    # high — explicit broad scope
    assert infer_signals("所有公司的报销标准", "broad", []).confidence == "high"
    # high — grounded entity + routing marker (比较 is a synthesis marker)
    assert infer_signals("比较甲公司的报销标准", "single", []).confidence == "high"
    # medium — grounded entity only (plain lookup)
    assert infer_signals("报销标准是什么", "single", []).confidence == "medium"
    # medium — multiple entities, no marker (could be accidental)
    assert infer_signals("甲公司和乙公司的地址", "multi_explicit", []).confidence == "medium"
    # medium — routing marker only, ungrounded (lone keyword never high)
    assert infer_signals("比较各项制度", "none", []).confidence == "medium"
    # low — neither grounded entity nor routing marker
    assert infer_signals("公司情况怎么样", "none", []).confidence == "low"


def test_provenance_defaults_are_deterministic():
    sig = infer_signals("报销标准是什么", "single", [])
    assert sig.source == "deterministic"
    assert sig.fallback_used is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_control_inferred.py::test_confidence_ladder_v1 backend/tests/unit/test_control_inferred.py::test_provenance_defaults_are_deterministic -v`
Expected: FAIL — `confidence` is constant `"high"`; `source`/`fallback_used` attributes do not exist.

- [ ] **Step 3: Implement**

In `backend/app/rag/query/control/inferred.py`, add the two fields to the dataclass (after `reasons`):

```python
@dataclass(frozen=True)
class InferredSignals:
    entity_scope: EntityScope
    needs_synthesis: bool
    needs_discovery: bool
    needs_multi_hop: bool
    requested_format: str | None = None
    confidence: str = "high"
    reasons: list[str] = field(default_factory=list)
    source: str = "deterministic"
    fallback_used: bool = False
```

Add the ladder helper (above `infer_signals`):

```python
def _confidence(entity_scope: str, has_routing_marker: bool) -> Literal["high", "medium", "low"]:
    """Deterministic confidence ladder v1 (design 2A §3).

    high   = explicit broad scope  OR  (grounded entity AND routing marker)
    medium = grounded entity only  OR  routing marker only
    low    = neither
    """
    grounded = entity_scope in ("single", "multi")
    if entity_scope == "broad" or (grounded and has_routing_marker):
        return "high"
    if grounded or has_routing_marker:
        return "medium"
    return "low"
```

In `infer_signals`, replace the hard-coded `confidence="high"` with the computed level and set provenance. The routing marker for v1 is "any deterministic intent signal" = synthesis marker or discovery keyword:

```python
    has_routing_marker = needs_synthesis or has_discovery_kw
    return InferredSignals(
        entity_scope=scope,
        needs_synthesis=needs_synthesis,
        needs_discovery=has_discovery_kw,
        needs_multi_hop=needs_multi_hop,
        requested_format=None,
        confidence=_confidence(scope, has_routing_marker),
        reasons=reasons,
        source="deterministic",
        fallback_used=False,
    )
```

- [ ] **Step 4: Run the new tests + the existing inferred suite**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_control_inferred.py -v`
Expected: PASS. Note: the existing `test_d1_invariants` uses a `broad`-scope query, so its `confidence == "high"` assertion still holds. If any *other* existing test asserts `confidence == "high"` on a non-broad/non-corroborated query, update it to the value the ladder now yields (the ladder is the new source of truth) — do **not** weaken the ladder.

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/query/control/inferred.py backend/tests/unit/test_control_inferred.py
git commit -m "feat(2A): graded confidence ladder v1 + intent provenance on InferredSignals"
```

---

## Task 2: `trust_gate` pure function

The promotion contract, born now and exercised in shadow only. High confidence → inferred route; otherwise the Design 1 route (the compat anchor). 2C activates it.

**Files:**
- Modify: `backend/app/rag/query/control/routing.py`
- Test: `backend/tests/unit/test_control_routing.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/test_control_routing.py`:

```python
def test_trust_gate_high_confidence_uses_inferred():
    from app.rag.query.control.routing import RoutingDecision, trust_gate
    from app.rag.query.control.inferred import infer_signals
    inferred = RoutingDecision(True, True, True, True, "inferred", "broad", "prose")
    design1 = RoutingDecision(False, False, False, False, "design1", "default", "prose")
    intent = infer_signals("所有公司的报销标准", "broad", [])   # high
    assert trust_gate(intent, inferred, design1) is inferred


def test_trust_gate_below_high_uses_design1():
    from app.rag.query.control.routing import RoutingDecision, trust_gate
    from app.rag.query.control.inferred import infer_signals
    inferred = RoutingDecision(True, True, True, True, "inferred", "broad", "prose")
    design1 = RoutingDecision(False, False, False, False, "design1", "default", "prose")
    intent = infer_signals("报销标准是什么", "single", [])      # medium
    assert trust_gate(intent, inferred, design1) is design1
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_control_routing.py::test_trust_gate_high_confidence_uses_inferred backend/tests/unit/test_control_routing.py::test_trust_gate_below_high_uses_design1 -v`
Expected: FAIL — `cannot import name 'trust_gate'`.

- [ ] **Step 3: Implement**

In `backend/app/rag/query/control/routing.py`, add (after `derive_routing_decision`):

```python
def trust_gate(
    intent: InferredSignals,
    inferred_decision: RoutingDecision,
    design1_decision: RoutingDecision,
) -> RoutingDecision:
    """Promotion contract (design 2A §4). Trust the inferred route only at high
    confidence; otherwise fall back to the current Design 1 route (the compat anchor).

    Shadow-only in 2A — never drives query_plan. In 2A the two decisions are the same
    deterministic value (the caller passes it as both args); they diverge in 2B.
    Activated in 2C.
    """
    return inferred_decision if intent.confidence == "high" else design1_decision
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_control_routing.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/query/control/routing.py backend/tests/unit/test_control_routing.py
git commit -m "feat(2A): add shadow-only trust_gate promotion contract"
```

---

## Task 3: `shadow_routing` trace + planner wiring

Enrich `routing_trace` with intent provenance and the `shadow_routing` section, computed at the existing `query_plan_node` seam. `diverged` uses **normalized-dict comparison** (not object identity / dataclass `__eq__`).

**Files:**
- Modify: `backend/app/rag/query/control/routing.py` (`build_routing_trace`)
- Modify: `backend/app/rag/query/planner.py` (`query_plan_node`)
- Test: `backend/tests/unit/test_control_routing.py`, `backend/tests/unit/test_query_stats.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_control_routing.py`:

```python
def test_trace_has_intent_provenance_and_shadow_routing():
    from app.rag.query.config import QueryConfig
    from app.rag.query.control.inferred import infer_signals
    from app.rag.query.control.routing import (
        build_routing_trace, derive_routing_decision,
    )
    cfg = QueryConfig()
    inferred = infer_signals("报销标准是什么", "single", [])      # medium
    decision = derive_routing_decision(inferred, "balanced", cfg, budget_reason="r")
    trace = build_routing_trace(inferred, "balanced", cfg, decision, decision)
    assert trace["intent"]["source"] == "deterministic"
    assert trace["intent"]["fallback_used"] is False
    sr = trace["shadow_routing"]
    assert sr["trust_gated"] is True            # medium → gate fires
    assert sr["diverged"] is False              # same decision both args
    assert "would_be_decision" in sr


def test_trace_shadow_records_forced_divergence_but_active_unchanged():
    import dataclasses
    from app.rag.query.config import QueryConfig
    from app.rag.query.control.inferred import infer_signals
    from app.rag.query.control.routing import (
        build_routing_trace, derive_routing_decision,
    )
    cfg = QueryConfig()
    inferred = infer_signals("报销标准是什么", "single", [])
    active = derive_routing_decision(inferred, "balanced", cfg, budget_reason="r")
    would_be = dataclasses.replace(active, use_multi_hop=not active.use_multi_hop)
    trace = build_routing_trace(inferred, "balanced", cfg, active, would_be)
    assert trace["shadow_routing"]["diverged"] is True                       # recorded
    assert trace["routing_decision"]["use_multi_hop"] == active.use_multi_hop  # active unchanged
```

Append to `backend/tests/unit/test_query_stats.py` (asserts the new keys *survive persistence*, not
just trace construction — Design 1 already surfaces `routing_trace` into `resolved_settings`):

```python
def test_2a_intent_provenance_and_shadow_survive_into_resolved_settings():
    from app.services.query_observability import build_query_observability_payload
    state = {
        "query_plan": {"retrieval_flavor": "balanced", "retrieval_breadth": "balanced",
                       "budget": {}, "fallback_policy": {}},
        "routing_trace": {
            "intent": {"confidence": "medium", "source": "deterministic", "fallback_used": False},
            "shadow_routing": {"would_be_decision": {"use_multi_hop": False},
                               "trust_gated": True, "diverged": False},
        },
    }
    rt = build_query_observability_payload(state=state)["resolved_settings"]["routing_trace"]
    assert rt["intent"]["source"] == "deterministic"
    assert rt["intent"]["fallback_used"] is False
    assert rt["shadow_routing"]["diverged"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_control_routing.py::test_trace_has_intent_provenance_and_shadow_routing backend/tests/unit/test_control_routing.py::test_trace_shadow_records_forced_divergence_but_active_unchanged -v`
Expected: FAIL — `build_routing_trace` takes 4 args (no `would_be_decision`); `intent` has no `source`; no `shadow_routing`.

- [ ] **Step 3: Implement the trace extension**

In `backend/app/rag/query/control/routing.py`, add `import dataclasses` and import `Confidence` from `control.inferred`, then replace `build_routing_trace` and add the `_shadow_routing` helper:

```python
def build_routing_trace(
    inferred: InferredSignals,
    breadth: RetrievalBreadth,
    cfg: QueryConfig,
    decision: RoutingDecision,
    would_be_decision: RoutingDecision,
) -> dict:
    """Trace the three tiers, the active derived decision, and the shadow routing record."""
    return {
        "intent": {
            "entity_scope": inferred.entity_scope,
            "needs_synthesis": inferred.needs_synthesis,
            "needs_discovery": inferred.needs_discovery,
            "needs_multi_hop": inferred.needs_multi_hop,
            "confidence": inferred.confidence,
            "source": inferred.source,
            "fallback_used": inferred.fallback_used,
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
        "shadow_routing": _shadow_routing(decision, would_be_decision, inferred.confidence),
    }


def _shadow_routing(
    active: RoutingDecision, would_be: RoutingDecision, confidence: Confidence,
) -> dict:
    """Record the would-be (trust-gated) decision."""
    would_be_dict = dataclasses.asdict(would_be)
    active_execution = _decision_execution_dict(active)
    would_be_execution = _decision_execution_dict(would_be)
    return {
        "would_be_decision": would_be_dict,
        "trust_gated": confidence != "high",
        "diverged": would_be_execution != active_execution,
    }


_EXECUTION_DECISION_FIELDS = (
    "use_hyde", "use_query_expansion", "use_multi_hop", "use_entity_fallback",
    "budget_reason", "prompt_variant", "answer_shape", "steps",
)


def _decision_execution_dict(decision: RoutingDecision) -> dict:
    """Return only behavior-bearing fields; reasons/vetoes are trace metadata."""
    return {field: getattr(decision, field) for field in _EXECUTION_DECISION_FIELDS}
```

- [ ] **Step 4: Wire the planner seam**

In `backend/app/rag/query/planner.py`, update `query_plan_node` (lines ~60-73) to compute the would-be decision and pass it through. In 2A both `trust_gate` args are the single deterministic `decision`:

```python
def query_plan_node(state: QueryState, config: RunnableConfig) -> dict:
    """Resolve high-level query controls into one plan plus routing trace."""
    from app.rag.query.control.routing import build_routing_trace, trust_gate

    cfg = get_query_config(config)
    query = require_query(state)
    entity_mode = state.get("entity_mode", "none")
    matched = list(state.get("matched_entities") or [])
    flavor, breadth, inferred, decision, budget = _resolve_routing(query, entity_mode, matched, cfg)
    plan = _plan_from_routing(flavor, breadth, decision, budget, cfg)
    would_be = trust_gate(inferred, decision, decision)  # 2A: same deterministic decision both args
    return {
        "query_plan": asdict(plan),
        "routing_trace": build_routing_trace(inferred, breadth, cfg, decision, would_be),
    }
```

- [ ] **Step 5: Run routing + planner + observability suites**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_control_routing.py backend/tests/unit/test_query_planner.py backend/tests/unit/test_query_stats.py -v`
Expected: PASS. If any test calls `build_routing_trace` with the old 4-arg signature, update that call to pass the active decision as the 5th arg (the only other caller is `query_plan_node`, updated above).

- [ ] **Step 6: Commit**

```bash
git add backend/app/rag/query/control/routing.py backend/app/rag/query/planner.py backend/tests/unit/test_control_routing.py backend/tests/unit/test_query_stats.py
git commit -m "feat(2A): shadow_routing trace section wired at the planner seam"
```

> Note: the `test_query_stats.py` persistence test is a **passthrough guard** — it passes
> immediately because Design 1 already surfaces `routing_trace` into `resolved_settings`. It locks
> in that the *new* `intent.source`/`fallback_used`/`shadow_routing.diverged` keys are carried
> through, so a future change to the observability filter can't silently drop them.

---

## Task 4: Full behavior-preservation verification

**Files:** none (verification only)

- [ ] **Step 1: Full backend unit suite**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit -q`
Expected: PASS. The Design-1 characterization net (`test_planner_characterization.py`) must still pass unchanged — that is the "emitted `query_plan` is byte-for-byte Design 1" guarantee.

- [ ] **Step 2: Golden-set retrieval-only (active-unchanged gate)**

Run (stack up):
```bash
docker compose exec -T backend sh -lc 'PYTHONPATH=/app python scripts/eval_golden_set.py --golden-set /app/data/challenge_golden_set_v1.jsonl --api-base http://127.0.0.1:8010/api --mode retrieval_only --concurrency 2 --delay 0 --case-timeout 240 --output /app/data/intent_2a_retrieval_only.jsonl'
```
This writes two artifacts: `data/intent_2a_retrieval_only.jsonl` (per-case) and
`data/intent_2a_retrieval_only_summary.json` (aggregates). Expected: **identical** to the accepted
Design 1 baseline — retrieval is unaffected by trace-only changes.
- Compare `Hit@5`/`Hit@10` in `data/intent_2a_retrieval_only_summary.json` against
  `data/control_model_retrieval_only_20260612_summary.json` (both must be `1.0`).
- Confirm per-case parity: the retrieved doc ids in `data/intent_2a_retrieval_only.jsonl` match
  `data/control_model_retrieval_only_20260612.jsonl`. Retrieval-only **must remain identical**.

- [ ] **Step 3: Golden-set full (active-unchanged gate)**

Run:
```bash
docker compose exec -T backend sh -lc 'PYTHONPATH=/app python scripts/eval_golden_set.py --golden-set /app/data/challenge_golden_set_v1.jsonl --api-base http://127.0.0.1:8010/api --mode full --judge --concurrency 2 --delay 0 --case-timeout 300 --output /app/data/intent_2a_full_judge.jsonl'
```
Expected: full pass rate (in `data/intent_2a_full_judge_summary.json`) matches the accepted Design 1
baseline (≈0.9355). Because 2A is trace-only it should not change any answer, **but the LLM judge can
vary** — so do not treat per-case status as a hard equality gate. Any case-level status change vs
`data/control_model_full_judge_20260612.jsonl` **must be investigated** (re-run the case; confirm the
answer text and citations are unchanged) rather than assumed to be a regression or accepted as noise.
The retrieval-only gate (Step 2) is the hard identity check; full-judge is the pass-rate + investigate gate.

- [ ] **Step 4: End-to-end spot-check (the unit test in Task 3 is the primary guarantee)**

The persistence path is already asserted by `test_2a_intent_provenance_and_shadow_survive_into_resolved_settings`
(Task 3). As a final end-to-end confirmation, after one real query through the stack, confirm
`query_run_stats.settings_json` contains `routing_trace.intent.source`,
`routing_trace.intent.fallback_used`, and `routing_trace.shadow_routing.diverged` (the latter
`false`) — proving the §5 path live, without a schema change.

---

## Self-Review (completed by plan author)

**Spec coverage:** graded confidence ladder v1 (§3 → Task 1) · `source`/`fallback_used` provenance, deterministic in 2A (§2 → Task 1) · `trust_gate` pure function, safe-default ≡ Design 1 route, one-decision-both-args in 2A (§4 → Task 2) · `shadow_routing` with normalized-dict `diverged`, planner-local at `_resolve_routing` seam, no new node (§5 → Task 3) · persistence of the new keys via existing `routing_trace`→`settings_json`, asserted by a unit test (Task 3) + e2e spot-check (Task 4), no schema change (§5) · active-unchanged + shadow-inert + forced-divergence-recorded tests (§7 → Tasks 1, 3, 4). Non-goals (no LLM, no `requested_format`, no golden set/metrics/activation, no discovery retirement, no rename) all honored.

**Placeholder scan:** none — every code step shows full code; every run step shows the command + expected result.

**Type consistency:** `InferredSignals` gains `source: str` / `fallback_used: bool` (Task 1) and they are read in `build_routing_trace` (Task 3); `trust_gate(intent, inferred_decision, design1_decision)` signature (Task 2) matches the `query_plan_node` call (Task 3); `build_routing_trace` gains a 5th param `would_be_decision`, and its sole caller is updated in the same task; `_shadow_routing` serializes the full would-be decision for observability but compares only behavior-bearing fields so `reasons`/`vetoes` cannot create false divergence.
