# Query-Intent Routing 2D Implementation Plan

**Status:** Executed on 2026-06-13. Gates passed.
**Design:** `docs/designs/query_intent_2d_design.md`.

**Goal:** Clean up 2C-3 active-path reporting, then retire the deprecated explicit `discovery`
breadth/flavor only if the named discovery-retirement gates stay green.

---

## Current State

Already shipped:

- 2C-3 active defaults: `intent.inline_enabled=true`, `intent.active_mode=true`.
- Runtime deployment activated with both flags true.
- 2D-A reporting cleanup: `report_inline_shadow.py` now reports observed rows, classifier runs,
  skipped rows, skip reasons, classifier run rate, and skip rate.

Current leading discovery-retirement candidate:

- Map legacy incoming `retrieval_flavor=discovery` to `retrieval_breadth=balanced`.
- Make `needs_discovery` first-class:
  - broad prompt for non-`multi` discovery intent, except `precise` keeps default prompt
  - explicit discovery-shaped balanced budget; multi-entity synthesis keeps synthesis budget
  - multi-hop still gated by `query.use_multi_hop`
- Pair retirement with `query.use_multi_hop=true` if broader gates pass, and bake that as the
  versioned `QueryConfig` default so fresh installs do not silently run the weaker Option 1 shape.
- Keep `intent.inline_enabled` and `intent.active_mode` for now; do not remove rollback in the same
  commit.

---

## Commit Boundaries

### Commit A — 2D-A report/readiness cleanup

Already shipped in `c906482`.

Files:

- `backend/scripts/report_inline_shadow.py`
- `backend/tests/unit/test_inline_shadow_report.py`
- `docs/designs/query_intent_2d_design.md`
- `docs/designs/query_intent_routing_roadmap.md`

Verification:

- `python -m pytest tests/unit/test_inline_shadow_report.py -q`
- `python -m pytest tests/unit -q`

### Commit B — Discovery retirement implementation

Behavior-changing. Gates passed on 2026-06-13.

Includes the versioned `QueryConfig` default change to `query.use_multi_hop=true` if the gates pass.

### Commit C — Operational activation of new multi-hop default

Only if Commit B lands and the final eval is green. Existing deployments need a runtime settings
update because DB values win over baked defaults.

---

## Task 1: Lock The Intended Discovery-Retirement Semantics

### Tests first

Update/add tests that express the new contract:

- `test_control_breadth.py`
  - `VALID_BREADTHS == {"precise", "balanced", "broad"}`
  - `resolve_breadth("discovery") == "balanced"` during the compatibility window
  - no `BREADTH_PROFILES["discovery"]`
- `test_control_budget.py`
  - `balanced + needs_discovery` has an explicit `balanced_discovery` budget
  - multi-entity synthesis keeps `balanced_synthesis` even when discovery is also marked
  - `precise` and `broad` behavior remains policy-owned
- `test_control_routing.py`
  - no `discovery` multi-hop bypass remains
  - `cfg.use_multi_hop=false` vetoes inferred discovery multi-hop
  - `needs_discovery=true` selects broad prompt for non-`multi` scopes except `precise`
  - `entity_scope=multi` still selects `multi_entity`
- `test_query_planner.py`
  - incoming `retrieval_flavor=discovery` emits `retrieval_flavor=balanced`,
    `retrieval_breadth=balanced`, and a deprecation trace
  - legacy discovery no longer disables fallback by itself
- `test_retrieval_test_service.py`
  - old discovery-bypass assertions are rewritten as migration-delta assertions
- `test_multi_hop.py`
  - multi-hop still runs when inferred discovery intent + `query.use_multi_hop=true`
  - multi-hop does not run when the infra flag is false
- `test_runtime_settings_defaults.py` / config-default coverage
  - versioned `QueryConfig` default is `use_multi_hop=true` once 2D-B lands
- `test_routing_golden_set_fixture.py`
  - remove `discovery` from allowed `retrieval_breadth` values if fixture rows change
- comparator tests, if `compare_activation_eval.py` is extended
  - expected discovery-retirement IDs are reported as allowed route changes, not leaks
  - non-allowlisted non-activatable route changes still fail the leak gate

### Contract details

The trace should name the compatibility input without preserving old behavior:

```json
{
  "policy": {
    "retrieval_breadth": "balanced",
    "legacy_retrieval_flavor": "discovery",
    "discovery_retired": true
  }
}
```

The emitted `query_plan["retrieval_flavor"]` should be `balanced`, not `discovery`, so stats and
eval artifacts reflect the retired behavior.

---

## Task 2: Implement The Route Semantics

Files:

- `backend/app/rag/query/control/breadth.py`
  - remove `discovery` from `RetrievalBreadth`, `VALID_BREADTHS`, and `BREADTH_PROFILES`
  - map legacy flavor `discovery -> balanced`
- `backend/app/rag/query/control/budget.py`
  - add a `needs_discovery` parameter to `resolve_budget_profile`
  - add `balanced_discovery` as the explicit budget reason
  - remove `discovery_current_path`
- `backend/app/rag/query/control/routing.py`
  - remove `breadth == "discovery"` bypass
  - broad prompt if `needs_discovery=true` and `entity_scope != "multi"`, except `precise`
- `backend/app/rag/query/planner.py`
  - preserve raw incoming flavor long enough to emit the deprecation trace
  - normalize emitted `retrieval_flavor` to `balanced` when raw input was `discovery`
  - pass `needs_discovery` into the budget resolver
- `backend/app/rag/query/diversify_context.py`
  - remove `discovery` from active flavor diversification
  - add `balanced_discovery` to budget-reason diversification
- `backend/app/rag/query/validate_citations.py`
  - stop keying fallback citations on `retrieval_flavor=discovery`
  - keep `hop_plan=discovery` / `entity_mode=multi_hop` support
- `backend/app/rag/query/config.py`
  - keep accepting `retrieval_flavor=discovery` during the compatibility window, but treat it as
    deprecated input
  - set the versioned `query.use_multi_hop` default to `true` if the gates pass
- `backend/app/services/query_stats_service.py`
  - keep historical `"discovery"` grouping support until the stats/UI migration; new rows should
    emit `balanced`
- `backend/scripts/compare_activation_eval.py`
  - add an expected-route-change allowlist, or equivalent non-discovery filtering, so intended
    discovery-retirement deltas do not masquerade as activation leaks

Do not remove `intent.active_mode` or `intent.inline_enabled` in this commit.

---

## Task 3: Focused Discovery Gates

Run from repo root unless noted:

```bash
cd /home/hao/workspace/enterprise_rag && source .venv/bin/activate && cd backend
```

Use host embedding path for local `retrieval_only`:

```bash
EMBEDDING_MODEL_PATH=/home/hao/models/BAAI/bge-m3
```

Required gates after implementation:

1. Unit suite:
   ```bash
   python -m pytest tests/unit -q
   ```
2. Routing golden scorer:
   ```bash
   python -m scripts.score_routing_golden_set \
     --corpus ../data/routing_golden_set_v1.jsonl \
     --output ../data/routing_golden_set_v1_scored.jsonl
   ```
   Gate: same 2C-1 safety gates remain green.
3. Discovery slice retrieval-only:
   ```bash
   EMBEDDING_MODEL_PATH=/home/hao/models/BAAI/bge-m3 \
   python -m scripts.eval_golden_set --golden-set ../data/challenge_golden_set_v1.jsonl \
     --mode retrieval_only --slice discovery \
     --runtime-setting intent.inline_enabled=true \
     --runtime-setting intent.active_mode=true \
     --runtime-setting query.use_multi_hop=true \
     --output ../data/eval_results/2d_discovery_retired_retrieval.jsonl
   ```
   Gate: no Hit@5/Hit@10 regression on discovery cases.
4. Discovery slice full/judge:
   - Set server-side `query.use_multi_hop=true`.
   - Run:
     ```bash
     python -m scripts.eval_golden_set --golden-set ../data/challenge_golden_set_v1.jsonl \
       --mode full --judge --slice discovery \
       --output ../data/eval_results/2d_discovery_retired_full_judge.jsonl
     ```
   - Restore server-side `query.use_multi_hop` if the gate fails.
   - Gate: no net answer-quality regression; manually inspect all five discovery cases.

---

## Task 4: Full-Set Blast Radius

The activation comparator's original leak invariant is "route changes must be activatable." That is
not true during discovery retirement: the five legacy discovery rows are expected to change
deterministically, and many of them are high-confidence rows where the classifier is skipped. Task 4
therefore must either compare a non-discovery-filtered slice or pass an expected-change allowlist.

Use the allowlist form so the full artifact is still inspected:

```text
discovery_multi_001
discovery_multi_002
discovery_multi_003
discovery_hop_001
discovery_hop_002
recall_agg_001
strict_002
```

First confirm the accepted 2C-3 ON baseline exists:

```bash
test -f ../data/eval_results/2c3_after_gate_on_retrieval.jsonl
```

Run full retrieval-only with `query.use_multi_hop=true`:

```bash
EMBEDDING_MODEL_PATH=/home/hao/models/BAAI/bge-m3 \
python -m scripts.eval_golden_set --golden-set ../data/challenge_golden_set_v1.jsonl \
  --mode retrieval_only \
  --runtime-setting intent.inline_enabled=true \
  --runtime-setting intent.active_mode=true \
  --runtime-setting query.use_multi_hop=true \
  --output ../data/eval_results/2d_full_challenge_retired_retrieval.jsonl
```

Compare against the latest accepted 2C-3 active retrieval artifact:

```bash
python -m scripts.compare_activation_eval \
  --off ../data/eval_results/2c3_after_gate_on_retrieval.jsonl \
  --on ../data/eval_results/2d_full_challenge_retired_retrieval.jsonl \
  --allowed-route-change-id discovery_multi_001 \
  --allowed-route-change-id discovery_multi_002 \
  --allowed-route-change-id discovery_multi_003 \
  --allowed-route-change-id discovery_hop_001 \
  --allowed-route-change-id discovery_hop_002 \
  --allowed-route-change-id recall_agg_001 \
  --allowed-route-change-id strict_002
```

Gate:

- `no_hit_regression=true`
- allowlisted discovery rows plus audited first-class discovery-intent rows are the only
  non-activatable deterministic route changes
- route changes outside the allowlist are activatable LLM improvements
- no unallowlisted non-activatable route leak

This is a full-set retrieval gate, not a full-set answer-quality gate. The plan accepts full-set
answer-quality impact from global `query.use_multi_hop=true` as post-flip-monitored risk because the
retrieval gate is green, the discovery slice gets full/judge coverage, and rollback is a single
runtime setting (`query.use_multi_hop=false`). If stronger pre-flip coverage is needed, add a full
`challenge_golden_set_v1 --mode full --judge` run before Commit C.

If route changes occur outside the discovery slice, decide whether to run full/judge on those cases
before committing.

Execution note: `recall_agg_001` and `strict_002` changed route through first-class discovery intent,
not legacy discovery retirement. They were kept in the allowlist only after full/judge coverage:
`aggregation` slice 2/2 pass, avg `1.000`; `strict` slice 2/2 pass, avg `1.000`.

---

## Task 5: Commit And Operate

If all gates pass:

1. Commit the code and tests.
2. Record the artifact paths and gate summary in `query_intent_2d_design.md`.
3. Operationally set:
   - `intent.inline_enabled=true`
   - `intent.active_mode=true`
   - `query.use_multi_hop=true`
4. Keep rollback ready:
   - `query.use_multi_hop=false` reverts the new multi-hop availability.
   - `intent.active_mode=false` reverts inferred-route driving.
   - `intent.inline_enabled=false` disables classifier calls entirely.

---

## Stop Conditions

Hard stop and ask for review if any of these happen:

- discovery slice Hit@K regression
- discovery slice full/judge regression not explainable as judge noise
- full-set Hit@K regression
- non-activatable route leak
- broad multi-hop enablement causes unexpected latency or answer-quality degradation
- implementation requires adding new deterministic keyword patterns

---

## Execution Summary (2026-06-13)

- Unit suite: `614 passed`
- Routing golden scorer: 40 cases; clear expected-route accuracy `0.9667`; clear wrong-route count
  `0`; ambiguous confident-wrong count `0`
- Discovery retrieval-only: Hit@5/Hit@10 `5/5`
- Discovery full/judge: avg `0.955`, pass rate `80%`, one `judge_uncertain` on
  `discovery_hop_001`
- Full challenge retrieval-only: 28 hit-bearing cases, Hit@5/Hit@10 `100%`
- Comparator: `no_leak=true`, `no_hit_regression=true`
- Runtime setting applied through `/api/settings`: `query.use_multi_hop=true`
