# Query-Intent Routing 2C-3 (Trust-Gated Activation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make high-confidence inferred routes actually drive `query_plan` by versioning the activation flags to `"true"`, gated on an offline eval go-gate enforced by a paired-run comparator.

**Architecture:** Two commits. Commit 1 ships eval-support tooling with defaults unchanged (`"false"`): surface `routing_trace` in the retrieval-test output, add an in-process runtime override for `retrieval_only` eval, and add a paired-run comparator that enforces the route leak check plus Hit@K non-regression. The operator then runs the paired eval via explicit runtime overrides. Commit 2 — only if the go-gate is green — flips the `_DEFAULTS` to `"true"` and lands a test-suite pin so the suite stays offline, plus permanent activation-regression protection.

**Tech Stack:** Python 3, pytest, SQLite-backed `runtime_settings`, the `eval_golden_set` harness (`--mode retrieval_only` runs `run_retrieval_test` in-process). Spec: `docs/designs/query_intent_2c3_design.md`.

---

## File structure

| File | Responsibility | Change |
| --- | --- | --- |
| `backend/app/services/retrieval_test_service.py` | retrieval-test execution | **Modify** — surface `routing_trace` in the return dict (one line) |
| `backend/scripts/eval_golden/cli.py` | eval CLI | **Modify** — add `--runtime-setting KEY=VALUE` for in-process `retrieval_only` overrides |
| `backend/scripts/compare_activation_eval.py` | paired-run leak-check comparator | **Create** — `compare_activation_runs` pure fn + DB-free file I/O `main` |
| `backend/app/core/runtime_settings.py` | runtime flag defaults | **Modify** — flip both `intent.*` defaults to `"true"` (Commit 2) |
| `backend/tests/conftest.py` | shared test fixtures | **Modify** — autouse fixture pinning both flags `"false"` (Commit 2) |
| `backend/tests/unit/test_retrieval_test_service.py` | retrieval-test tests | **Modify** — assert `routing_trace` is surfaced |
| `backend/tests/unit/test_eval_golden_set_config.py` | eval CLI tests | **Modify** — assert runtime override writes the local cache |
| `backend/tests/unit/test_compare_activation_eval.py` | comparator tests | **Create** — leak detection unit test |
| `backend/tests/unit/test_query_planner.py` | planner tests | **Modify** — activation-regression protection |
| `backend/tests/unit/test_runtime_settings_defaults.py` | shipped-default guard | **Create** — assert baked defaults are `"true"` |

**Commit boundaries (spec-mandated):**
- **Commit 1 = Task 1 + Task 2** (eval tooling; defaults stay `"false"`; no default-behavior change).
- **Operational go-gate** = Task 3 (manual; paired eval via runtime overrides + comparator).
- **Commit 2 = Task 4 + Task 5** (bake defaults + suite pin + permanent protection) — **only if Task 3 is green.**

**Test runner:** from repo root, `source .venv/bin/activate` once, then run pytest from `backend/`:
```bash
cd /home/hao/workspace/enterprise_rag && source .venv/bin/activate && cd backend
```

---

### Task 1: Surface `routing_trace` in the retrieval-test output

The leak check needs per-case activation evidence. `run_retrieval_test` runs the real `query_plan_node`
(`retrieval_test_service.py:52`, `search_pipeline.py:142`), so `state["routing_trace"]` (with
`inline_shadow`) is already populated — it is just not returned. `--mode retrieval_only` eval runs
`run_retrieval_test` in-process (`scripts/eval_golden/runner.py:176-182`) and stores the whole return
dict under `row["retrieval_step"]`, so this one line carries activation evidence into eval artifacts.

**2C-3 dry-run refinement:** OFF-vs-OFF retrieval-only runs showed ranked-key churn even when
route/plan fields and Hit@K were unchanged. Therefore the comparator reports ranked-key changes as
diagnostics, but the hard leak gate is route-bearing fields only; Hit@5/Hit@10 regression remains a
separate hard gate.

The same dry run showed timeout fallbacks taking more than one inline timeout window because the
shared classifier helper allowed one client retry. 2C-3 keeps that retry for offline replay, but the
inline path must pass `max_retries=0`. A later paired run showed a 6s request timeout still exceeding
the 6000ms wall-clock p95 gate, so the inline request timeout default is tuned to 4s; 6000ms remains
the promotion gate.

**Files:**
- Modify: `backend/app/services/retrieval_test_service.py:93`
- Modify: `backend/app/rag/query/control/llm_classifier.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/unit/test_retrieval_test_service.py`
- Test: `backend/tests/unit/test_llm_classifier.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/test_retrieval_test_service.py` (mirrors the existing
`test_run_retrieval_test_returns_strategy_and_paths` harness):

```python
def test_run_retrieval_test_surfaces_routing_trace(monkeypatch):
    monkeypatch.setattr(svc, "get_default_query_config", lambda: QueryConfig(use_table_expand=False))
    monkeypatch.setattr(svc, "_entity_confirm_node", _noop_entity_confirm)
    monkeypatch.setattr(svc, "_rewrite_query_node", _noop_rewrite)
    monkeypatch.setattr(svc, "_search_node", lambda state, config: {
        "search_mode": "hybrid",
        "search_results": [],
    })
    monkeypatch.setattr(svc, "_hyde_search_node", lambda state, config: {
        "search_mode_hyde": "disabled",
        "search_results_hyde": [],
    })
    monkeypatch.setattr(svc, "_table_expand_node", _noop_table_expand)

    payload = svc.run_retrieval_test(
        "差旅报销需要什么材料？",
        top_k=5,
        use_hybrid=True,
        use_hyde=False,
        use_rerank=False,
    )

    assert "routing_trace" in payload
    # flags default off (and conftest pins them off), so the inline classifier is inert
    assert payload["routing_trace"]["inline_shadow"]["ran"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/unit/test_retrieval_test_service.py::test_run_retrieval_test_surfaces_routing_trace -q`
Expected: FAIL with `KeyError: 'routing_trace'`.

- [ ] **Step 3: Surface the field**

In `backend/app/services/retrieval_test_service.py`, in the `run_retrieval_test` return dict, add the
line immediately after `"query_plan": state.get("query_plan", {}),`:

```python
        "query_plan": state.get("query_plan", {}),
        "routing_trace": state.get("routing_trace", {}),
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/unit/test_retrieval_test_service.py -q`
Expected: PASS (all existing + 1 new).

- [ ] **Step 5: Do NOT commit yet** — this lands with Task 2 as Commit 1.

---

### Task 2: Eval runtime override + paired-run comparator (the enforceable leak check)

**Files:**
- Modify: `backend/scripts/eval_golden/cli.py`
- Create: `backend/scripts/compare_activation_eval.py`
- Test: `backend/tests/unit/test_eval_golden_set_config.py`
- Test: `backend/tests/unit/test_compare_activation_eval.py`

- [ ] **Step 1: Add and test the in-process eval runtime override**

`retrieval_only` eval runs in the script process, and planner flags are read from the synchronous
`runtime_settings._cache`. A settings-API update in the running app does **not** populate this fresh
script process, so the retrieval-only ON/OFF pair needs an explicit local override.

Add to `backend/tests/unit/test_eval_golden_set_config.py`:

```python
def test_eval_cli_runtime_setting_override_updates_local_cache():
    from app.core.runtime_settings import runtime_settings
    from scripts.eval_golden import cli

    prev = dict(runtime_settings._cache)
    try:
        runtime_settings._cache.clear()
        cli._apply_runtime_overrides([
            "intent.inline_enabled=true",
            "intent.active_mode=true",
        ])
        assert runtime_settings.get_cached("intent.inline_enabled") == "true"
        assert runtime_settings.get_cached("intent.active_mode") == "true"
    finally:
        runtime_settings._cache = prev
```

Run: `python -m pytest tests/unit/test_eval_golden_set_config.py::test_eval_cli_runtime_setting_override_updates_local_cache -q`
Expected: FAIL — `_apply_runtime_overrides` does not exist.

In `backend/scripts/eval_golden/cli.py`, add:

```python
    parser.add_argument("--runtime-setting", action="append", default=[],
                        help="Override local runtime_settings cache for this eval process: KEY=VALUE")
```

Immediately before `run_eval(...)`, call:

```python
    _apply_runtime_overrides(args.runtime_setting)
```

Add the helper:

```python
def _apply_runtime_overrides(items: list[str]) -> None:
    if not items:
        return
    from app.core.runtime_settings import runtime_settings

    for item in items:
        if "=" not in item:
            raise SystemExit(f"Invalid --runtime-setting {item!r}; expected KEY=VALUE")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise SystemExit(f"Invalid --runtime-setting {item!r}; key is empty")
        runtime_settings._cache[key] = value.strip()
```

This override is for in-process eval paths, especially `--mode retrieval_only`. Full/answer eval calls
the running API over HTTP; for those runs, toggle the server via the settings API instead.

Run the new test again. Expected: PASS.

- [ ] **Step 2: Write the failing comparator test**

Create `backend/tests/unit/test_compare_activation_eval.py`. Import inside the test (deferred), matching
the `scripts.*` pattern in `test_routing_golden_set_fixture.py:50`:

```python
def _row(case_id, *, keys, hit5, hit10, expansion, activatable):
    return {
        "id": case_id,
        "hit_at_5": hit5,
        "hit_at_10": hit10,
        "rerank_results": [{"chunk_key": k, "document_id": f"doc-{k}"} for k in keys],
        "retrieval_step": {
            "query_plan": {
                "use_hyde": True,
                "use_query_expansion": expansion,
                "use_multi_hop": False,
                "fallback_policy": {"entity_filter_to_global": False},
                "retrieval_breadth": "balanced",
                "strict_evidence": False,
                "budget": {"search_limit": 10, "reason": "balanced_current_defaults"},
                "prompt_policy": {"template": "default"},
            },
            "routing_trace": {
                "routing_decision": {
                    "use_hyde": True,
                    "use_query_expansion": expansion,
                    "use_multi_hop": False,
                    "use_entity_fallback": False,
                    "budget_reason": "balanced_current_defaults",
                    "prompt_variant": "default",
                    "answer_shape": "prose",
                    "steps": [],
                },
                "inline_shadow": {"activatable_diverged": activatable},
            },
        },
    }


def test_comparator_flags_non_activatable_change_as_leak():
    from scripts.compare_activation_eval import compare_activation_runs

    off = {
        "a": _row("a", keys=["k1"], hit5=True, hit10=True, expansion=False, activatable=False),
        "b": _row("b", keys=["k1"], hit5=True, hit10=True, expansion=False, activatable=False),
        "c": _row("c", keys=["k1"], hit5=True, hit10=True, expansion=False, activatable=False),
    }
    on = {
        # a: activatable AND changed -> intended flip, not a leak
        "a": _row("a", keys=["k2"], hit5=True, hit10=True, expansion=True, activatable=True),
        # b: NOT activatable but changed -> leak
        "b": _row("b", keys=["k9"], hit5=True, hit10=True, expansion=False, activatable=False),
        # c: unchanged
        "c": _row("c", keys=["k1"], hit5=True, hit10=True, expansion=False, activatable=False),
    }
    summary = compare_activation_runs(off, on)
    assert summary["changed_ids"] == ["a", "b"]
    assert summary["activatable_ids"] == ["a"]
    assert summary["leak_ids"] == ["b"]
    assert summary["gates"]["no_leak"] is False


def test_comparator_clean_when_only_activatable_change():
    from scripts.compare_activation_eval import compare_activation_runs

    off = {"a": _row("a", keys=["k1"], hit5=True, hit10=True, expansion=False, activatable=False)}
    on = {"a": _row("a", keys=["k2"], hit5=True, hit10=True, expansion=True, activatable=True)}
    summary = compare_activation_runs(off, on)
    assert summary["leak_ids"] == []
    assert summary["gates"]["no_leak"] is True
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m pytest tests/unit/test_compare_activation_eval.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.compare_activation_eval'`.

- [ ] **Step 4: Implement the comparator**

Create `backend/scripts/compare_activation_eval.py`:

```python
"""Paired-run leak check for Design 2C-3 activation.

Compares an `active-OFF` and an `inline+active-ON` retrieval_only eval artifact and asserts that the
set of cases whose normalized behavior changed is a subset of the activatable set. Standalone —
archived after the flip; never imported by live code.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# Normalized behavior-bearing fields. Timing and classifier telemetry are deliberately excluded —
# they differ whenever inline runs.
_DECISION_FIELDS = (
    "use_hyde",
    "use_query_expansion",
    "use_multi_hop",
    "use_entity_fallback",
    "budget_reason",
    "prompt_variant",
    "answer_shape",
    "steps",
)


def _behavior(row: dict[str, Any]) -> dict[str, Any]:
    retrieval = row.get("retrieval_step") or {}
    plan = retrieval.get("query_plan") or {}
    trace = retrieval.get("routing_trace") or {}
    decision = trace.get("routing_decision") or {}
    prompt_policy = plan.get("prompt_policy") or {}
    fallback_policy = plan.get("fallback_policy") or {}
    return {
        "ranked_keys": [
            r.get("chunk_key") or r.get("document_id") or ""
            for r in row.get("rerank_results") or []
        ],
        "hit_at_5": row.get("hit_at_5"),
        "hit_at_10": row.get("hit_at_10"),
        "decision": {
            field: decision.get(field)
            for field in _DECISION_FIELDS
        } if decision else {
            "use_hyde": plan.get("use_hyde"),
            "use_query_expansion": plan.get("use_query_expansion"),
            "use_multi_hop": plan.get("use_multi_hop"),
            "use_entity_fallback": fallback_policy.get("entity_filter_to_global"),
            "budget_reason": (plan.get("budget") or {}).get("reason"),
            "prompt_variant": prompt_policy.get("template"),
            "answer_shape": None,
            "steps": None,
        },
        "fallback_policy": fallback_policy,
        "retrieval_breadth": plan.get("retrieval_breadth"),
        "strict_evidence": plan.get("strict_evidence"),
        "budget": plan.get("budget"),
    }


def _activatable(row: dict[str, Any]) -> bool:
    trace = (row.get("retrieval_step") or {}).get("routing_trace") or {}
    return bool((trace.get("inline_shadow") or {}).get("activatable_diverged"))


def compare_activation_runs(off_rows: dict[str, dict], on_rows: dict[str, dict]) -> dict[str, Any]:
    """Compare paired runs keyed by case id. Pure function."""
    common = [cid for cid in off_rows if cid in on_rows]
    changed_ids = [cid for cid in common if _behavior(off_rows[cid]) != _behavior(on_rows[cid])]
    activatable_ids = [cid for cid in common if _activatable(on_rows[cid])]
    activatable_set = set(activatable_ids)
    leak_ids = [cid for cid in changed_ids if cid not in activatable_set]
    return {
        "common": len(common),
        "changed_ids": changed_ids,
        "activatable_ids": activatable_ids,
        "leak_ids": leak_ids,
        "gates": {"no_leak": len(leak_ids) == 0},
    }


def _load_rows(path: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            rows[row["id"]] = row
    return rows


def main() -> None:
    args = _parse_args()
    summary = compare_activation_runs(_load_rows(args.off), _load_rows(args.on))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["gates"]["no_leak"]:
        print(f"\nLEAK: non-activatable cases changed: {summary['leak_ids']}", file=sys.stderr)
        sys.exit(1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare paired activation eval runs (2C-3 leak check)")
    parser.add_argument("--off", required=True, help="active-OFF retrieval_only results JSONL")
    parser.add_argument("--on", required=True, help="inline+active-ON retrieval_only results JSONL")
    return parser.parse_args()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/unit/test_compare_activation_eval.py -q`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit (Commit 1 — eval tooling, defaults unchanged)**

```bash
git add backend/app/services/retrieval_test_service.py \
  backend/tests/unit/test_retrieval_test_service.py \
  backend/scripts/eval_golden/cli.py \
  backend/tests/unit/test_eval_golden_set_config.py \
  backend/scripts/compare_activation_eval.py \
  backend/tests/unit/test_compare_activation_eval.py
git commit -m "feat(2C-3): eval-support tooling for activation leak check (defaults unchanged)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Run the offline go-gate (manual, no code)

Gate the flip on evidence. Defaults are still `"false"`; drive the ON run with runtime overrides. Do
**not** proceed to Commit 2 unless this is green.

- [ ] **Step 1: Confirm preconditions**

2C-1 gates green (`../data/routing_golden_set_v1_scored_summary.json` from `backend/`, or the
equivalent current scorer artifact), 2C-2 shadow report green +
`activatable_diverged` rows audited.

- [ ] **Step 2: Baseline run (active OFF)**

Run from `backend/`. Use `--runtime-setting` because `retrieval_only` reads the local script process's
`runtime_settings._cache`:
```bash
python -m scripts.eval_golden_set --golden-set ../data/challenge_golden_set_v1.jsonl \
  --mode retrieval_only \
  --runtime-setting intent.inline_enabled=false \
  --runtime-setting intent.active_mode=false \
  --output ../data/eval_results/2c3_off_retrieval.jsonl
```

- [ ] **Step 3: Activated retrieval-only run (inline + active ON via in-process override)**

```bash
python -m scripts.eval_golden_set --golden-set ../data/challenge_golden_set_v1.jsonl \
  --mode retrieval_only \
  --runtime-setting intent.inline_enabled=true \
  --runtime-setting intent.active_mode=true \
  --output ../data/eval_results/2c3_on_retrieval.jsonl
```
No reset is needed for these two runs; the override is process-local.

- [ ] **Step 4: Run the leak-check comparator**

Run:
```bash
python -m scripts.compare_activation_eval \
  --off ../data/eval_results/2c3_off_retrieval.jsonl \
  --on ../data/eval_results/2c3_on_retrieval.jsonl
```
Expected: `gates.no_leak == true` and `gates.no_hit_regression == true` (exit 0). Any `leak_ids` is a
hard stop — a non-activatable case changed route-bearing fields, which is a wiring bug, not intent.
`ranked_key_changed_ids` is diagnostic because baseline retrieval can reorder/change candidates across
identical OFF runs.

- [ ] **Step 5: Answer-quality run + audit**

Run the answer-quality pair against the running API. Unlike `retrieval_only`, this goes over HTTP, so
toggle the server-side settings via the settings API/runtime settings on the running app before each
run.

With server flags OFF:
```bash
python -m scripts.eval_golden_set --golden-set ../data/challenge_golden_set_v1.jsonl \
  --mode full --judge --output ../data/eval_results/2c3_off_full.jsonl
```

With server flags ON:
```bash
python -m scripts.eval_golden_set --golden-set ../data/challenge_golden_set_v1.jsonl \
  --mode full --judge --output ../data/eval_results/2c3_on_full.jsonl
```
Reset server flags to `"false"` afterward until Commit 2 is ready.

Confirm no net answer-quality regression vs the logged baseline; investigate every case-change
(judge noise is expected — confirm flips are improvements or neutral, never degradations). Re-confirm
each `activatable_diverged` route is wanted.

Only if Steps 4 and 5 are green, proceed to Task 4.

---

### Task 4: Bake activation + suite pin (Commit 2)

**Files:**
- Modify: `backend/app/core/runtime_settings.py:25-29`
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/unit/test_runtime_settings_defaults.py`

- [ ] **Step 1: Write the failing shipped-default test**

Create `backend/tests/unit/test_runtime_settings_defaults.py`. It reads the baked `_DEFAULTS` directly
(not `_cache`), so it is unaffected by the autouse pin:

```python
def test_intent_flags_default_to_active():
    from app.core.runtime_settings import _DEFAULTS

    assert _DEFAULTS["intent.inline_enabled"] == "true"
    assert _DEFAULTS["intent.active_mode"] == "true"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/unit/test_runtime_settings_defaults.py -q`
Expected: FAIL — defaults are still `"false"`.

- [ ] **Step 3: Add the autouse suite pin FIRST**

In `backend/tests/conftest.py`, add (so the suite stays offline once defaults flip):

```python
@pytest.fixture(autouse=True)
def _pin_intent_flags_off():
    from app.core.runtime_settings import runtime_settings

    prev = dict(runtime_settings._cache)
    runtime_settings._cache["intent.inline_enabled"] = "false"
    runtime_settings._cache["intent.active_mode"] = "false"
    yield
    runtime_settings._cache = prev
```

- [ ] **Step 4: Flip the defaults**

In `backend/app/core/runtime_settings.py`, change the two `intent.*` entries in `_DEFAULTS.update({...})`:

```python
_DEFAULTS.update(
    {
        "intent.inline_enabled": "true",
        "intent.active_mode": "true",
    }
)
```

- [ ] **Step 5: Run the full suite (must stay green and offline)**

Run: `python -m pytest tests/unit -q`
Expected: PASS, with no network calls. The autouse pin keeps every `query_plan_node` test on the
deterministic path; the 2C-2 inline/active tests still opt in via `monkeypatch.setitem` (which runs
after the autouse fixture). The shipped-default test passes (reads `_DEFAULTS`).

- [ ] **Step 6: Do NOT commit yet** — lands with Task 5 as Commit 2.

---

### Task 5: Permanent activation-regression protection (Commit 2)

**Files:**
- Test: `backend/tests/unit/test_query_planner.py`

- [ ] **Step 1: Write the protection test**

Append to `backend/tests/unit/test_query_planner.py` (the flag helpers `_set_flags`, `_divergent_high`,
`_STATE`, `_CONFIG` from the 2C-2 tests already exist in this file; reuse them):

```python
def test_activation_drives_high_confidence_route_when_flags_on(monkeypatch):
    monkeypatch.setattr(llm_classifier, "classify_intent_inline", _divergent_high())
    _set_flags(monkeypatch, inline=False, active=False)
    baseline = query_plan_node(_STATE, _CONFIG)["query_plan"]

    _set_flags(monkeypatch, inline=True, active=True)
    out = query_plan_node(_STATE, _CONFIG)
    # high-confidence divergent intent drives: route + budget differ from deterministic
    assert out["query_plan"]["budget"] != baseline["budget"] or \
        out["routing_trace"]["routing_decision"]["answer_shape"] == "bullets_or_table"
    assert out["routing_trace"]["intent"]["source"] == "llm_escalated"


def test_activation_falls_back_on_classifier_failure(monkeypatch):
    state = {"query": "哪些公司提到了安全计划？", "entity_mode": "broad"}
    monkeypatch.setattr(
        llm_classifier, "classify_intent_inline", _divergent_high(reason="timeout", markers=False)
    )
    _set_flags(monkeypatch, inline=False, active=False)
    baseline = query_plan_node(state, _CONFIG)["query_plan"]

    _set_flags(monkeypatch, inline=True, active=True)
    out = query_plan_node(state, _CONFIG)
    assert out["query_plan"] == baseline  # failed classifier never drives
    assert out["routing_trace"]["intent"]["fallback_used"] is False  # emitted intent is deterministic
```

- [ ] **Step 2: Run the test (passes against current 2C-2 wiring)**

Run: `python -m pytest tests/unit/test_query_planner.py -q`
Expected: PASS. This is permanent protection — the gate logic already shipped in 2C-2; these tests lock
the activated behavior so a future change can't silently regress it.

- [ ] **Step 3: Commit (Commit 2 — bake activation)**

```bash
git add backend/app/core/runtime_settings.py \
  backend/tests/conftest.py \
  backend/tests/unit/test_runtime_settings_defaults.py \
  backend/tests/unit/test_query_planner.py
git commit -m "feat(2C-3): activate trust-gated inferred routing by default

Versions intent.inline_enabled + intent.active_mode to true (runtime override
remains the instant rollback). Suite pinned deterministic via autouse fixture.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 4: Activate the running deployment (operational)**

The baked default only covers fresh installs; the existing DB rows win
(`runtime_settings.get_cached` reads `_cache` before `_DEFAULTS`). Set both keys `"true"` via the
settings API / `runtime_settings.set` on the running deployment. Keep the raw eval artifacts under
`../data/eval_results/2c3_*` (ignored by `.gitignore`); commit a concise closeout note with the artifact
paths, summary metrics, and activation decision. Hold `intent.active_mode="false"` ready as instant
rollback.

---

## Self-review

**Spec coverage:**
- Surface `routing_trace` for eval evidence → **Task 1**.
- In-process runtime override for `retrieval_only` eval → **Task 2** (`--runtime-setting` writes the
  local `runtime_settings._cache`, avoiding the fresh-process cache trap).
- Paired-run comparator / enforceable leak check over normalized fields → **Task 2** (`_route_behavior`
  uses routing-decision execution fields, fallback policy, breadth/strict flags, and full budget;
  `hit_at_5/10` are a separate hard non-regression gate; ranked `chunk_key or document_id` changes are
  diagnostic only after OFF-vs-OFF showed baseline rank churn; excludes timing/classifier telemetry per
  Finding 3).
- Offline go-gate (retrieval_only leak + non-regression, `--mode full --judge` answer quality, audit) →
  **Task 3** (correct CLI: `--mode retrieval_only`, `--mode full --judge`).
- Versioned defaults flipped to `"true"` + suite pin → **Task 4**.
- Permanent activation-regression protection + shipped-default guard → **Task 5** + **Task 4**.
- Existing-deployment activation (DB wins over baked default) → **Task 5, Step 4**.
- Two-commit split (tooling first, bake only if green) → Commit 1 = Tasks 1–2; Commit 2 = Tasks 4–5,
  gated on Task 3.

**Type/fact consistency:** comparator reads `row["retrieval_step"]["routing_trace"]["inline_shadow"]
["activatable_diverged"]` and `row["rerank_results"][*]["chunk_key" or "document_id"]` /
`row["hit_at_5"]` — matching the `run_retrieval_only_case` row shape (`runner.py`) and `format_result`
(`chunk_key`, `document_id`). `routing_trace` lands under `retrieval_step` because the runner stores the
whole `run_retrieval_test` return there. `_set_flags`/`_divergent_high`/`_STATE`/`_CONFIG` are reused
from the 2C-2 `test_query_planner.py` additions.

**Placeholder scan:** none — every code step is complete; the only manual task (Task 3) is operational
by nature, like 2C-1/2C-2 closeouts.

**Behavioral note:** `build_query_plan` never runs the inline seam, so `test_planner_characterization.py`
is unaffected by the default flip and needs no change.
