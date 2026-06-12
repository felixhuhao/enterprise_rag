# Design 2C-1 — Routing Golden Set + Correctness Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a labeled routing golden set and an offline scorer that grades the **post-gate** route from LLM-enriched intent against expected routing intent — producing the correctness evidence the 2C activation gate needs. **No production code, no behavior change.**

**Architecture:** A new labeled corpus `data/routing_golden_set_v1.jsonl` + a script `backend/scripts/score_routing_golden_set.py` that, per case, runs the shipped pipeline (`infer_signals → classify_intent_llm → merge_intent → route → trust_gate`), derives `expected_route` via the decision table, and classifies the outcome. The pure outcome-classification + budget-per-intent route helper are unit-tested; the script is integration-run.

**Tech Stack:** Python 3.12, pytest, sqlite-free (reads a jsonl corpus). Spec: `docs/designs/query_intent_2c1_design.md`.

**Invariant:** the scorer reuses shipped 2A/2B units only and adds **no** request-path code; the main golden set / eval is untouched.

---

## File Structure

**Create:**
- `data/routing_golden_set_v1.jsonl` — ~40 labeled cases (§2 of spec).
- `backend/app/rag/query/control/route_scoring.py` — pure scoring units: `build_expected_intent`, `route_for_intent`, `score_case` (testable without an LLM).
- `backend/scripts/score_routing_golden_set.py` — CLI: load corpus → run pipeline → aggregate → artifacts + gate verdicts.
- `backend/tests/unit/test_route_scoring.py` — unit tests for the pure units.
- `backend/tests/unit/test_routing_golden_set_fixture.py` — fixture-integrity test over the corpus.

**Modify:**
- `.gitignore` — add `!data/routing_golden_set_v1.jsonl` (root ignores `data/*`).

**Reused (shipped, unchanged):** `infer_signals`, `classify_intent_llm`, `merge_intent`, `derive_routing_decision`, `resolve_budget_profile`, `trust_gate`, `decision_execution_dict`, `InferredSignals`.

---

## Task 1: Pure scoring units (`route_scoring.py`)

The testable core: build the expected-intent object, resolve a route per intent (budget-per-intent), and classify the post-gate outcome. No LLM, no I/O.

**Files:**
- Create: `backend/app/rag/query/control/route_scoring.py`
- Test: `backend/tests/unit/test_route_scoring.py`

- [ ] **Step 1: Write the failing tests**

```python
from app.rag.query.config import QueryConfig
from app.rag.query.control.inferred import InferredSignals
from app.rag.query.control.route_scoring import (
    build_expected_intent, route_for_intent, score_case,
)


def test_build_expected_intent_rederives_multi_hop():
    # discovery over none-scope → needs_multi_hop re-derived true
    exp = build_expected_intent({"entity_scope": "none", "needs_synthesis": False,
                                 "needs_discovery": True})
    assert exp.needs_multi_hop is True
    # synthesis on single-scope → multi_hop false (scope gate)
    exp2 = build_expected_intent({"entity_scope": "single", "needs_synthesis": True,
                                  "needs_discovery": False})
    assert exp2.needs_multi_hop is False


def test_route_for_intent_uses_per_intent_budget():
    cfg = QueryConfig()
    plain = InferredSignals("single", False, False, False)
    synth = InferredSignals("single", True, False, False)
    # synthesis intent must pick the synthesis budget profile (different budget_reason)
    assert route_for_intent(plain, "balanced", cfg).budget_reason == "balanced_current_defaults"
    assert route_for_intent(synth, "balanced", cfg).budget_reason == "balanced_synthesis"


def _exec(**over):
    base = {"use_hyde": False, "use_query_expansion": False, "use_multi_hop": False,
            "use_entity_fallback": False, "budget_reason": "balanced_current_defaults",
            "prompt_variant": "default", "answer_shape": "prose", "steps": []}
    base.update(over)
    return base


def test_score_clear_correct_and_missed_and_wrong():
    expected = _exec(use_multi_hop=True)
    # correct + activated
    r = score_case("clear", True, "high", actual=_exec(use_multi_hop=True),
                   expected=expected, design1=_exec())
    assert r["route_correct"] and not r["wrong_route"] and not r["missed_activation"]
    # safe-defaulted (not high) but must_activate → missed_activation, route may be wrong
    r2 = score_case("clear", True, "medium", actual=_exec(), expected=expected, design1=_exec())
    assert r2["missed_activation"] and not r2["route_correct"] and not r2["wrong_route"]
    # activated to a wrong route → wrong_route (dangerous)
    r3 = score_case("clear", True, "high", actual=_exec(use_hyde=True),
                    expected=expected, design1=_exec())
    assert r3["wrong_route"] and not r3["route_correct"]


def test_score_ambiguous_safe_pass_vs_confident_wrong():
    expected = _exec(use_multi_hop=True)
    design1 = _exec()
    # not high + actual==design1 → safe default + safe pass
    r = score_case("ambiguous", False, "low", actual=design1, expected=expected, design1=design1)
    assert r["ambiguous_safe_default"] and r["ambiguous_safe_pass"] and not r["ambiguous_confident_wrong"]
    # high + actual==design1 but != expected → confident wrong (gate check, not route equality)
    r2 = score_case("ambiguous", False, "high", actual=design1, expected=expected, design1=design1)
    assert r2["ambiguous_confident_wrong"] and not r2["ambiguous_safe_pass"] and not r2["ambiguous_safe_default"]
    # correct route at high → safe pass (not safe-default, since activated)
    r3 = score_case("ambiguous", False, "high", actual=expected, expected=expected, design1=design1)
    assert r3["ambiguous_safe_pass"] and not r3["ambiguous_confident_wrong"] and not r3["ambiguous_safe_default"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_route_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: ...route_scoring`.

- [ ] **Step 3: Implement**

Create `backend/app/rag/query/control/route_scoring.py`:

```python
"""Pure scoring units for the 2C-1 routing golden set (no LLM, no I/O)."""

from __future__ import annotations

from typing import Any, Mapping

from app.rag.query.config import QueryConfig
from app.rag.query.control.budget import resolve_budget_profile
from app.rag.query.control.inferred import InferredSignals
from app.rag.query.control.routing import (
    RoutingDecision, decision_execution_dict, derive_routing_decision,
)


def build_expected_intent(expected: Mapping[str, Any]) -> InferredSignals:
    """Build the labeled expected intent; needs_multi_hop is re-derived (never labeled)."""
    scope = str(expected["entity_scope"])
    needs_synthesis = bool(expected.get("needs_synthesis", False))
    needs_discovery = bool(expected.get("needs_discovery", False))
    needs_multi_hop = scope in ("broad", "none") and needs_discovery
    return InferredSignals(
        entity_scope=scope,
        needs_synthesis=needs_synthesis,
        needs_discovery=needs_discovery,
        needs_multi_hop=needs_multi_hop,
    )


def route_for_intent(intent: InferredSignals, breadth: str, cfg: QueryConfig) -> RoutingDecision:
    """Resolve budget PER intent, then derive the route (budget_reason is an execution field)."""
    budget = resolve_budget_profile(breadth, intent.entity_scope, intent.needs_synthesis, cfg)
    return derive_routing_decision(intent, breadth, cfg, budget_reason=budget.reason)


def score_case(
    case_class: str,
    must_activate: bool,
    confidence: str,
    *,
    actual: RoutingDecision | Mapping[str, Any],
    expected: RoutingDecision | Mapping[str, Any],
    design1: RoutingDecision | Mapping[str, Any],
) -> dict:
    """Classify one case's post-gate outcome. Route accuracy and activation are orthogonal."""
    actual_x = decision_execution_dict(actual)
    expected_x = decision_execution_dict(expected)
    design1_x = decision_execution_dict(design1)

    route_correct = actual_x == expected_x
    activated = confidence == "high"
    actual_eq_design1 = actual_x == design1_x

    is_clear = case_class == "clear"
    is_amb = case_class == "ambiguous"
    return {
        "case_class": case_class,
        "must_activate": must_activate,
        "route_correct": route_correct,
        "activated": activated,
        # clear axes
        "missed_activation": is_clear and must_activate and not activated,
        "wrong_route": is_clear and activated and not route_correct,
        # ambiguous axes (safe-pass checks the GATE, not just route equality)
        "ambiguous_safe_default": is_amb and not activated and actual_eq_design1,
        "ambiguous_safe_pass": is_amb and (route_correct or (not activated and actual_eq_design1)),
        "ambiguous_confident_wrong": is_amb and activated and not route_correct,
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_route_scoring.py -v`
Expected: PASS (4)

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/query/control/route_scoring.py backend/tests/unit/test_route_scoring.py
git commit -m "feat(2C-1): pure route-scoring units (expected intent, per-intent budget, outcome)"
```

---

## Task 2: The routing golden set corpus + fixture integrity test

The corpus is data, so the "test" is a fixture-integrity check that fails until the corpus is authored correctly — including the `entity_scope` consistency assertion from the spec.

**Files:**
- Create: `data/routing_golden_set_v1.jsonl`, `backend/tests/unit/test_routing_golden_set_fixture.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write the failing fixture-integrity test**

```python
import json
from pathlib import Path

from app.rag.query.control.inferred import infer_signals

CORPUS = Path(__file__).resolve().parents[3] / "data" / "routing_golden_set_v1.jsonl"
FUZZY = {"implicit_synthesis", "paraphrase", "discovery_unspecified",
         "discovery_no_keyword", "multi_hop_altphrase"}
VALID_CATEGORIES = FUZZY | {"clear_control"}


def _load():
    return [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_corpus_size_and_categories():
    cases = _load()
    assert 35 <= len(cases) <= 48, f"expected ~40 cases, got {len(cases)}"
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate ids"
    by_cat = {}
    for c in cases:
        assert c["category"] in VALID_CATEGORIES, c["category"]
        assert c["case_class"] in {"clear", "ambiguous"}
        by_cat.setdefault(c["category"], []).append(c)
    for fuzzy_cat in FUZZY:
        n = len(by_cat.get(fuzzy_cat, []))
        assert 6 <= n <= 8, f"{fuzzy_cat}: expected 6-8, got {n}"
    n_control = len(by_cat.get("clear_control", []))
    assert 5 <= n_control <= 8, f"clear_control: expected 5-8, got {n_control}"


def test_every_case_entity_scope_is_consistent():
    # spec §3: entity_scope is a consistency check, not an authority — fixture errors on mismatch.
    for c in _load():
        det = infer_signals(c["query"], c["entity_mode"], c.get("matched_entities", []))
        assert det.entity_scope == c["expected_intent"]["entity_scope"], (
            f"{c['id']}: deterministic scope {det.entity_scope} != "
            f"labeled {c['expected_intent']['entity_scope']}"
        )


def test_clear_cases_have_full_markers_ambiguous_have_acceptable():
    for c in _load():
        ei = c["expected_intent"]
        assert "entity_scope" in ei
        if c["case_class"] == "clear":
            assert "needs_synthesis" in ei and "needs_discovery" in ei
        else:
            assert c.get("acceptable") == "expected_route_or_safe_default"
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_routing_golden_set_fixture.py -v`
Expected: FAIL — corpus file does not exist.

- [ ] **Step 3: Author the corpus + allowlist it**

Add to `.gitignore` (next to `!data/challenge_golden_set_v1.jsonl`):

```
!data/routing_golden_set_v1.jsonl
```

Author `data/routing_golden_set_v1.jsonl` — one JSON object per line — to the §2 category mix
(6-8 each of `implicit_synthesis`, `paraphrase`, `discovery_unspecified`, `discovery_no_keyword`,
`multi_hop_altphrase`; 5-8 `clear_control`; 2-3 `ambiguous` *within* each fuzzy category's count),
~40 total. **Authoring rules:** queries must avoid the existing trigger words for their category
(no `比较/区别/异同/对比` in implicit-synthesis; no `哪些公司/竞争对手/各自/分别` in discovery; no
`谁负责/由谁负责/负责人` in multi-hop); `entity_scope` must equal what `infer_signals` derives for the
given `entity_mode` (the fixture test enforces this); use `retrieval_breadth`. Seed examples (extend
to the full mix):

```json
{"id": "implicit_synthesis_001", "category": "implicit_synthesis", "case_class": "clear", "query": "甲公司和乙公司在报销上是不是一回事？", "entity_mode": "multi_explicit", "matched_entities": ["甲公司", "乙公司"], "retrieval_breadth": "balanced", "strict_evidence": false, "expected_intent": {"entity_scope": "multi", "needs_synthesis": true, "needs_discovery": false}, "must_activate": true}
{"id": "discovery_no_keyword_001", "category": "discovery_no_keyword", "case_class": "clear", "query": "API迁移指南归谁写？", "entity_mode": "none", "matched_entities": [], "retrieval_breadth": "balanced", "strict_evidence": false, "expected_intent": {"entity_scope": "none", "needs_synthesis": false, "needs_discovery": true}, "must_activate": true}
{"id": "discovery_unspecified_001", "category": "discovery_unspecified", "case_class": "clear", "query": "这套报销流程牵涉到哪几边？", "entity_mode": "none", "matched_entities": [], "retrieval_breadth": "balanced", "strict_evidence": false, "expected_intent": {"entity_scope": "none", "needs_synthesis": false, "needs_discovery": true}, "must_activate": true}
{"id": "paraphrase_001", "category": "paraphrase", "case_class": "clear", "query": "How does 甲公司's reimbursement differ from 乙公司's?", "entity_mode": "multi_explicit", "matched_entities": ["甲公司", "乙公司"], "retrieval_breadth": "balanced", "strict_evidence": false, "expected_intent": {"entity_scope": "multi", "needs_synthesis": true, "needs_discovery": false}, "must_activate": true}
{"id": "multi_hop_altphrase_001", "category": "multi_hop_altphrase", "case_class": "clear", "query": "出了数据泄露这事儿，最后是落到谁头上？", "entity_mode": "none", "matched_entities": [], "retrieval_breadth": "balanced", "strict_evidence": false, "expected_intent": {"entity_scope": "none", "needs_synthesis": false, "needs_discovery": true}, "must_activate": true}
{"id": "clear_control_001", "category": "clear_control", "case_class": "clear", "query": "比较甲公司和乙公司的报销标准", "entity_mode": "multi_explicit", "matched_entities": ["甲公司", "乙公司"], "retrieval_breadth": "balanced", "strict_evidence": false, "expected_intent": {"entity_scope": "multi", "needs_synthesis": true, "needs_discovery": false}, "must_activate": true}
{"id": "ambiguous_discovery_001", "category": "discovery_no_keyword", "case_class": "ambiguous", "query": "报销这块还有别的吗？", "entity_mode": "none", "matched_entities": [], "retrieval_breadth": "balanced", "strict_evidence": false, "expected_intent": {"entity_scope": "none", "needs_synthesis": false, "needs_discovery": true}, "acceptable": "expected_route_or_safe_default"}
```

> The user reviews these labels during execution; the fixture test guarantees structural + scope
> integrity regardless.

- [ ] **Step 4: Run the fixture test**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_routing_golden_set_fixture.py -v`
Expected: PASS. Any `entity_scope` mismatch names the offending case id — fix that case's
`entity_mode`/label until consistent.

- [ ] **Step 5: Commit**

```bash
git add .gitignore data/routing_golden_set_v1.jsonl backend/tests/unit/test_routing_golden_set_fixture.py
git commit -m "feat(2C-1): routing golden set v1 corpus + fixture-integrity test"
```

---

## Task 3: The scorer script + metric aggregation

Wire the corpus through the shipped pipeline, score each case, aggregate the §5 metrics, evaluate the §6 gates, emit artifacts. The aggregation is unit-tested with pre-scored rows; the LLM run is integration.

**Files:**
- Create: `backend/scripts/score_routing_golden_set.py`
- Test: `backend/tests/unit/test_route_scoring.py` (extend with aggregation test)

- [ ] **Step 1: Write the failing aggregation test**

Append to `backend/tests/unit/test_route_scoring.py`:

```python
def test_aggregate_metrics_and_gates():
    from app.rag.query.control.route_scoring import aggregate
    # 2 clear (1 correct+activated, 1 missed_activation), 1 ambiguous safe-pass
    rows = [
        {"case_class": "clear", "must_activate": True, "route_correct": True,  "activated": True,
         "missed_activation": False, "wrong_route": False,
         "ambiguous_safe_default": False, "ambiguous_safe_pass": False, "ambiguous_confident_wrong": False,
         "deterministic_route_correct": False, "category": "implicit_synthesis",
         "expected_markers": {"needs_synthesis": True, "needs_discovery": False},
         "merged_markers": {"needs_synthesis": True, "needs_discovery": False}},
        {"case_class": "clear", "must_activate": True, "route_correct": False, "activated": False,
         "missed_activation": True, "wrong_route": False,
         "ambiguous_safe_default": False, "ambiguous_safe_pass": False, "ambiguous_confident_wrong": False,
         "deterministic_route_correct": False, "category": "discovery_no_keyword",
         "expected_markers": {"needs_synthesis": False, "needs_discovery": True},
         "merged_markers": {"needs_synthesis": False, "needs_discovery": False}},
        {"case_class": "ambiguous", "must_activate": False, "route_correct": True, "activated": True,
         "missed_activation": False, "wrong_route": False,
         "ambiguous_safe_default": False, "ambiguous_safe_pass": True, "ambiguous_confident_wrong": False,
         "deterministic_route_correct": True, "category": "paraphrase",
         "expected_markers": {"needs_synthesis": False, "needs_discovery": True},
         "merged_markers": {"needs_synthesis": False, "needs_discovery": True}},
    ]
    s = aggregate(rows)
    assert s["clear_expected_route_accuracy"] == 0.5
    assert s["clear_missed_activation_rate"] == 0.5
    assert s["clear_wrong_route_count"] == 0
    assert s["ambiguous_confident_wrong_count"] == 0
    assert s["ambiguous_safe_default_rate"] == 0.0
    assert s["ambiguous_safe_pass_rate"] == 1.0
    assert s["llm_vs_deterministic_delta"] == 0.5   # 0.5 clear acc − 0.0 det clear acc
    assert s["marker_precision_recall"]["needs_synthesis"]["precision"] == 1.0
    assert s["marker_precision_recall"]["needs_discovery"]["recall"] == 0.5
    assert s["clear_control_route_regression_count"] == 0
    assert "per_category" in s
    assert s["per_category"]["implicit_synthesis"]["count"] == 1
    assert s["gates"]["clear_expected_route_accuracy>=0.9"] is False
    assert s["gates"]["ambiguous_confident_wrong_count==0"] is True
    assert s["gates"]["clear_wrong_route_count==0"] is True
    assert s["gates"]["clear_control_route_regression_count==0"] is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_route_scoring.py::test_aggregate_metrics_and_gates -v`
Expected: FAIL — `cannot import name 'aggregate'`.

- [ ] **Step 3: Implement `aggregate` in `route_scoring.py`**

```python
def aggregate(rows: list[dict]) -> dict:
    clear = [r for r in rows if r["case_class"] == "clear"]
    amb = [r for r in rows if r["case_class"] == "ambiguous"]

    def rate(items, key):
        return round(sum(1 for r in items if r[key]) / len(items), 4) if items else 0.0

    clear_acc = rate(clear, "route_correct")
    det_clear_acc = rate(clear, "deterministic_route_correct")

    must_activate_clear = [r for r in clear if r.get("must_activate")]
    clear_missed = rate(must_activate_clear, "missed_activation")

    amb_safe_default = sum(1 for r in amb if r.get("ambiguous_safe_default"))
    amb_safe_pass = rate(amb, "ambiguous_safe_pass")
    clear_control_regressions = [
        r for r in clear
        if r.get("category") == "clear_control" and not r.get("route_correct")
    ]

    def marker_pr(items: list[dict], field: str) -> dict:
        tp = sum(
            1 for r in items
            if r.get("merged_markers", {}).get(field) is True
            and r.get("expected_markers", {}).get(field) is True
        )
        fp = sum(
            1 for r in items
            if r.get("merged_markers", {}).get(field) is True
            and r.get("expected_markers", {}).get(field) is not True
        )
        fn = sum(
            1 for r in items
            if r.get("merged_markers", {}).get(field) is not True
            and r.get("expected_markers", {}).get(field) is True
        )
        return {
            "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
            "recall": round(tp / (tp + fn), 4) if (tp + fn) else None,
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }

    def metric_block(items: list[dict]) -> dict:
        block_clear = [r for r in items if r["case_class"] == "clear"]
        block_amb = [r for r in items if r["case_class"] == "ambiguous"]
        block_must_activate = [r for r in block_clear if r.get("must_activate")]
        block_clear_acc = rate(block_clear, "route_correct")
        block_det_clear_acc = rate(block_clear, "deterministic_route_correct")
        return {
            "count": len(items),
            "clear_expected_route_accuracy": block_clear_acc,
            "clear_missed_activation_rate": rate(block_must_activate, "missed_activation"),
            "clear_wrong_route_count": sum(1 for r in block_clear if r["wrong_route"]),
            "ambiguous_safe_default_rate": rate(block_amb, "ambiguous_safe_default"),
            "ambiguous_safe_pass_rate": rate(block_amb, "ambiguous_safe_pass"),
            "ambiguous_confident_wrong_count": sum(1 for r in block_amb if r["ambiguous_confident_wrong"]),
            "deterministic_clear_accuracy": block_det_clear_acc,
            "llm_vs_deterministic_delta": round(block_clear_acc - block_det_clear_acc, 4),
            "marker_precision_recall": {
                "needs_synthesis": marker_pr(items, "needs_synthesis"),
                "needs_discovery": marker_pr(items, "needs_discovery"),
            },
        }

    categories = sorted({r.get("category", "unknown") for r in rows})
    per_category = {
        cat: metric_block([r for r in rows if r.get("category") == cat])
        for cat in categories
    }

    summary = {
        "counts": {"total": len(rows), "clear": len(clear), "ambiguous": len(amb)},
        "clear_expected_route_accuracy": clear_acc,
        "clear_missed_activation_rate": clear_missed,
        "clear_wrong_route_rate": rate(clear, "wrong_route"),
        "clear_wrong_route_count": sum(1 for r in clear if r["wrong_route"]),
        "ambiguous_safe_default_rate": round(amb_safe_default / len(amb), 4) if amb else 0.0,
        "ambiguous_safe_pass_rate": amb_safe_pass,
        "ambiguous_confident_wrong_count": sum(1 for r in amb if r["ambiguous_confident_wrong"]),
        "deterministic_clear_accuracy": det_clear_acc,
        "llm_vs_deterministic_delta": round(clear_acc - det_clear_acc, 4),
        "clear_control_route_regression_count": len(clear_control_regressions),
        "clear_control_route_regression_ids": [r.get("id") for r in clear_control_regressions],
        "marker_precision_recall": {
            "needs_synthesis": marker_pr(rows, "needs_synthesis"),
            "needs_discovery": marker_pr(rows, "needs_discovery"),
        },
        "per_category": per_category,
    }
    summary["gates"] = {
        "clear_expected_route_accuracy>=0.9": clear_acc >= 0.9,
        "ambiguous_confident_wrong_count==0": summary["ambiguous_confident_wrong_count"] == 0,
        "clear_wrong_route_count==0": summary["clear_wrong_route_count"] == 0,
        "llm_vs_deterministic_delta>=0": summary["llm_vs_deterministic_delta"] >= 0,
        "clear_control_route_regression_count==0": summary["clear_control_route_regression_count"] == 0,
    }
    return summary
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_route_scoring.py -v`
Expected: PASS (5)

- [ ] **Step 5: Write the scorer script**

Create `backend/scripts/score_routing_golden_set.py`:

```python
"""Offline scorer for the 2C-1 routing golden set (design query_intent_2c1_design.md).

Per case: infer_signals -> classify_intent_llm -> merge_intent -> route() -> trust_gate,
derive expected_route, score the post-gate outcome, aggregate metrics + gates.
Reuses shipped 2A/2B units only; adds no production code."""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

from app.rag.query.config import QueryConfig
from app.rag.query.control.inferred import infer_signals
from app.rag.query.control.llm_classifier import classify_intent_llm
from app.rag.query.control.inferred import merge_intent
from app.rag.query.control.routing import decision_execution_dict, trust_gate
from app.rag.query.control.route_scoring import (
    aggregate, build_expected_intent, route_for_intent, score_case,
)

def _resolve_repo_root() -> Path:
    script_parent = Path(__file__).resolve().parent
    candidates = [
        script_parent.parent.parent,  # repo root when running from backend/scripts/
        script_parent.parent,         # /app when running from Docker /app/scripts/
        Path("/app"),
        Path.cwd(),
    ]
    for candidate in candidates:
        if (candidate / "data").is_dir():
            return candidate
    return Path(".")


REPO_ROOT = _resolve_repo_root()
DEFAULT_CORPUS = REPO_ROOT / "data" / "routing_golden_set_v1.jsonl"


def _cfg_for(case: dict) -> QueryConfig:
    # Infra flags default ON so the test isolates intent->route (vetoes don't mask the signal).
    cfg = QueryConfig()
    cfg.use_hyde = bool(case.get("enable_hyde", True))
    cfg.use_query_expansion = bool(case.get("enable_query_expansion", True))
    cfg.use_multi_hop = bool(case.get("enable_multi_hop", True))
    cfg.strict_evidence = bool(case.get("strict_evidence", False))
    return cfg


def score_one(case: dict) -> dict:
    breadth = str(case["retrieval_breadth"])
    cfg = _cfg_for(case)
    det = infer_signals(case["query"], case["entity_mode"], case.get("matched_entities", []))
    llm = classify_intent_llm(case["query"], det)
    merged = merge_intent(det, llm)
    expected = build_expected_intent(case["expected_intent"])

    design1_decision = route_for_intent(det, breadth, cfg)
    merged_decision = route_for_intent(merged, breadth, cfg)
    expected_route = route_for_intent(expected, breadth, cfg)
    actual_route = trust_gate(merged, merged_decision, design1_decision)

    outcome = score_case(
        case["case_class"], bool(case.get("must_activate", False)), merged.confidence,
        actual=actual_route, expected=expected_route, design1=design1_decision,
    )
    # deterministic baseline: the gate is inert (det route == design1) → accuracy vs expected
    det_outcome = score_case(
        case["case_class"], bool(case.get("must_activate", False)), det.confidence,
        actual=design1_decision, expected=expected_route, design1=design1_decision,
    )
    outcome["deterministic_route_correct"] = det_outcome["route_correct"]
    outcome["id"] = case["id"]
    outcome["category"] = case["category"]
    outcome["must_activate"] = bool(case.get("must_activate", False))
    outcome["fallback_used"] = merged.fallback_used
    outcome["merged"] = dataclasses.asdict(merged)
    outcome["actual_execution"] = decision_execution_dict(actual_route)
    outcome["expected_execution"] = decision_execution_dict(expected_route)
    outcome["design1_execution"] = decision_execution_dict(design1_decision)
    outcome["expected_markers"] = {
        k: v for k, v in case["expected_intent"].items()
        if k in ("needs_synthesis", "needs_discovery", "needs_multi_hop")
    }
    outcome["merged_markers"] = {
        "needs_synthesis": merged.needs_synthesis,
        "needs_discovery": merged.needs_discovery,
        "needs_multi_hop": merged.needs_multi_hop,
    }
    return outcome


def main() -> None:
    args = _parse_args()
    corpus = Path(args.corpus)
    cases = [json.loads(line) for line in corpus.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [score_one(c) for c in cases]
    summary = aggregate(rows)
    summary["fallback_rate"] = round(sum(1 for r in rows if r["fallback_used"]) / len(rows), 4) if rows else 0.0

    out = Path(args.output or (REPO_ROOT / "data" / "routing_golden_set_v1_scored.jsonl"))
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    out.with_name(out.stem + "_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Score the 2C-1 routing golden set")
    p.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    p.add_argument("--output", default=None)
    return p.parse_args()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/rag/query/control/route_scoring.py backend/scripts/score_routing_golden_set.py backend/tests/unit/test_route_scoring.py
git commit -m "feat(2C-1): routing golden set scorer + metric aggregation + gates"
```

---

## Task 4: Run the scorer + gate review

**Files:** none (verification only)

- [ ] **Step 1: Full unit suite (no behavior change)**

Run: `PYTHONPATH=backend .venv/bin/pytest backend/tests/unit/test_route_scoring.py backend/tests/unit/test_routing_golden_set_fixture.py backend/tests/unit/test_planner_characterization.py -q`
Expected: PASS. The characterization net confirms no production code changed.

- [ ] **Step 2: Run the scorer over the corpus (requires LLM access)**

Run (stack up / LLM reachable):
```bash
docker compose exec -T backend sh -lc 'PYTHONPATH=/app python scripts/score_routing_golden_set.py'
```
Expected: prints the summary with the §5 metrics and the `gates` block. Writes
`data/routing_golden_set_v1_scored.jsonl` + `_summary.json`.

- [ ] **Step 3: Review the gate verdicts**

Confirm: `clear_expected_route_accuracy >= 0.9`; `ambiguous_confident_wrong_count == 0`;
`clear_wrong_route_count == 0`; `llm_vs_deterministic_delta >= 0`; clear-control rows show no
route regression. **Any `wrong_route` or `confident_wrong` case is inspected individually** (read the
`merged` intent + the query) — at this corpus size each is review-worthy, not noise. The summary +
verdicts are the evidence carried into 2C-2 / 2C-3.

---

## Self-Review (completed by plan author)

**Spec coverage:** corpus §2 (Task 2, with category enum + ~40 size enforced by the fixture test) · case schema §3 incl. `entity_scope` consistency error (Task 2 fixture test) · per-intent budget + post-gate scoring §4 (`route_for_intent`, `score_case`, Task 1; wired in `score_one`, Task 3) · metrics §5 (`aggregate`, Task 3) · gates §6 (`aggregate.gates` + Task 4 review) · infra-flags-ON isolation §4 (`_cfg_for`, Task 3) · reuses shipped units only, no production code §7 (File Structure) · `.gitignore` allowlist §7 (Task 2). Non-goals (no inline/flags/activation/discovery-retirement) all honored.

**Placeholder scan:** none — corpus authoring carries seed examples + explicit rules + a failing fixture gate; all code steps show full code.

**Type consistency:** `build_expected_intent` / `route_for_intent` / `score_case` / `aggregate` signatures defined in Task 1/3 match `score_one`'s calls in Task 3; `score_case` returns the exact keys `aggregate` consumes; `decision_execution_dict` accepts both `RoutingDecision` and dict (used on shipped decisions). `classify_intent_llm` is sync (called directly).
