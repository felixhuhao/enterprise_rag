# Query-Intent Routing 2D Design

**Status:** Draft after 2C-3 activation. Implementation plan not written yet.
**Depends on:** 2C-3 active-mode closeout (`36f1caa`, `4260324`) and the 2C-1 routing golden set.

2D has two different jobs that should not be collapsed into one commit:

1. **Activation-scaffolding cleanup:** make the live inferred-intent path easier to observe and,
   later, remove shadow-only fields once active routing has proven boring.
2. **Discovery retirement:** remove the deprecated `discovery` breadth/flavor only after inferred
   `needs_discovery` has taken over its useful behavior and every delta is named and measured.

The second job is a behavior migration. It should not ride along with the first.

---

## 1. Current Evidence

2C-3 is active in the running deployment:

- `intent.inline_enabled=true`
- `intent.active_mode=true`
- Unit suite: `609 passed`
- 2C-1 routing golden set: clear expected-route accuracy `93.33%`, clear wrong-route count `0`,
  ambiguous confident-wrong count `0`
- 2C-3 paired retrieval-only gate: `route_changed_ids=[]`, `leak_ids=[]`,
  `hit_regression_ids=[]`, `activatable_ids=[]`

Post-activation smoke showed the intended positive flips:

- Clear comparison/paraphrase cases can activate into `llm_escalated`,
  `answer_shape=bullets_or_table`, `budget_reason=balanced_synthesis`.
- High-confidence deterministic broad cases skip the classifier with
  `skip_reason=high_confidence`.
- Low-confidence timeout/error cases fall back to the deterministic route.

But active-mode is not yet "boring" enough to delete rollback/scaffolding blindly:

- Small persisted smoke: 3 classifier runs, 2 timeout fallbacks, 1 activatable route.
- A later retrieval-only smoke had 3 classifier runs, 0 timeouts, 2 activatable routes.
- The variability is acceptable because the trust gate falls back safely, but it argues for keeping
  a runtime kill switch during 2D-A.

---

## 2. 2D-A: Activation-Scaffolding Cleanup

### Goal

Improve active-path observability and trim only scaffolding that is demonstrably obsolete.

### Recommendation

Do **not** delete both runtime flags immediately.

Keep at least one runtime kill switch until the active path has a longer observation window. The
current safest shape is:

- `intent.inline_enabled` remains the kill switch for classifier cost/latency failures.
- `intent.active_mode` can be retired later, once rollback via `inline_enabled=false` is considered
  sufficient.

This means 2D-A is mostly reporting and naming cleanup first, not a mechanical deletion.

### Immediate cleanup

`report_inline_shadow.py` should report both denominators:

- observed rows that carried `inline_shadow`
- classifier-run rows where `inline_shadow.ran=true`
- skipped rows and `skip_reason` counts

After 2C-3's below-high gate, reporting only "volume = classifier runs" hides high-confidence skips
and makes the active window look smaller than it is.

### Later cleanup, after approval

Once active routing proves stable enough:

- Remove or collapse `intent.active_mode`.
- Rename `_inline_intent` to the permanent classifier/gate helper.
- Keep fallback telemetry (`fallback_reason`, `fallback_used`, `latency_ms`, `confidence`,
  `merged_source`, `merged_reasons`).
- Delete shadow-only comparison fields when they stop serving operational audits:
  `proposal_execution`, `proposal_diverged`, `activatable_diverged`.
- Archive `scripts/report_inline_shadow.py` only after replacement active-path reporting exists.

### Non-goals

- No discovery retirement in 2D-A.
- No removal of `intent.inline_enabled` without explicit approval.
- No change to trust-gate semantics.

---

## 3. What `discovery` Means Today

Current `retrieval_flavor=discovery` resolves to a real deprecated breadth row:

| Dimension | Current `discovery` behavior |
| --- | --- |
| breadth | `discovery` |
| HyDE | off |
| query expansion | off |
| entity fallback | off |
| budget | current/default-size retrieval: `10/20/10/final 10/8000` |
| prompt | `broad`, except `multi_entity` still wins |
| multi-hop | permitted and bypasses `cfg.use_multi_hop` |

Measured against likely replacements with `use_multi_hop=false`:

| Query shape | `balanced` | `recall`/`broad` | current `discovery` |
| --- | --- | --- | --- |
| broad keyword (`哪些公司...`) | HyDE on, no expansion, no multi-hop, `balanced_broad` budget | expansion on, no multi-hop, recall-wide budget | no HyDE/expansion, multi-hop on, current-size budget |
| responsibility, no entity (`谁负责...`) | HyDE on, default prompt/budget, no multi-hop | expansion on, recall-wide budget, no multi-hop | broad prompt, multi-hop on, current-size budget |
| multi explicit comparison | balanced synthesis budget, `multi_entity` prompt | recall-wide budget, expansion on | current-size budget, no expansion, `multi_entity` prompt |
| plain single lookup | HyDE on, fallback on, default prompt | expansion on, fallback on, recall-wide budget | no HyDE/expansion/fallback, broad prompt |

So retiring `discovery` is not a rename. It changes at least budget, prompt, fallback, expansion,
HyDE, and the multi-hop infra bypass.

---

## 4. 2D-B: Discovery Retirement

### Goal

Remove task-typed explicit `discovery` selection from the breadth model. Discovery should be inferred
from query intent (`needs_discovery`), while breadth remains user policy (`precise | balanced |
broad`).

### Proposed Steady State

Valid breadths:

```text
precise | balanced | broad
```

`retrieval_flavor` remains the external config field for now. The external field rename to
`retrieval_breadth` is still a separate migration.

Legacy flavor mapping:

| Incoming `retrieval_flavor` | New breadth |
| --- | --- |
| `exact` | `precise` |
| `balanced` | `balanced` |
| `recall` | `broad` |
| `discovery` | `balanced` plus a deprecation trace |

The deprecation trace is for measurement only, not behavior compatibility:

```json
{
  "legacy_retrieval_flavor": "discovery",
  "retrieval_breadth": "balanced",
  "discovery_retired": true
}
```

### Intent-Owned Discovery Semantics

`needs_discovery` becomes a first-class routing signal:

- Prompt: for non-`multi` scopes, `needs_discovery=true` uses the broad prompt. `multi_entity`
  prompt still wins for `entity_scope=multi`.
- Budget: `balanced + needs_discovery` should use a discovery-shaped balanced budget. The initial
  candidate is `balanced_broad` for coverage, but this must be validated because it widens current
  single/none responsibility queries.
- Multi-hop: `needs_multi_hop` is still derived from `entity_scope in {broad, none}` and
  `needs_discovery`, but `cfg.use_multi_hop` applies. The old `discovery` bypass is removed.
- Fallback: fallback remains breadth policy. There is no special "discovery disables fallback"
  rule after retirement.
- HyDE/expansion: remain breadth-owned. `balanced` may use HyDE; `broad` may use expansion; `precise`
  suppresses both.

### Policy Precedence

Policy still beats intent:

- `precise` suppresses multi-hop even if `needs_discovery=true`.
- `strict_evidence` suppresses entity-to-global fallback.
- `enable_multi_hop=false` suppresses multi-hop after the old `discovery` bypass is removed.

### The Multi-Hop Default Question

The current app default is `use_multi_hop=false`. Today, explicit `discovery` bypasses that default.
After retirement, inferred discovery will not run multi-hop unless the infra flag is enabled.

That is the main open operational decision:

- Option 1: keep `use_multi_hop=false`; discovery retirement intentionally removes automatic
  multi-hop from legacy discovery traffic.
- Option 2: flip `query.use_multi_hop=true` as part of the migration; the bypass is gone, but
  multi-hop becomes available by default.
- Option 3: defer discovery retirement until multi-hop has its own readiness gate.

I recommend Option 3 unless a focused discovery eval shows no Hit@K or answer-quality regression
with Option 1 or Option 2. This is the one place where deleting the legacy knob can easily remove
real retrieval capability.

---

## 5. Evidence Gates For Discovery Retirement

Before removing the `discovery` breadth row:

1. Run a focused discovery slice of `challenge_golden_set_v1` under current behavior.
2. Run the same slice under the proposed retired behavior.
3. Compare:
   - route-bearing fields
   - Hit@5 / Hit@10
   - answer quality when route changes
   - citations/fallback behavior
4. Audit every `preferred_flavor=discovery` case manually.
5. Re-run `routing_golden_set_v1` and require:
   - clear expected-route accuracy remains >= 90%
   - clear wrong-route count remains 0
   - ambiguous confident-wrong count remains 0
   - no clear-control regression

Expected route deltas must be named in the summary:

- `discovery_current_path` budget -> balanced/broad discovery-shaped budget
- broad prompt now triggered by `needs_discovery`, not discovery breadth
- old multi-hop bypass removed
- fallback now follows breadth
- HyDE/expansion now follow breadth

No unnamed accepted delta.

---

## 6. Implementation Shape

### 2D-A files

- `backend/scripts/report_inline_shadow.py`
- `backend/tests/unit/test_inline_shadow_report.py`
- Later only: `planner.py`, `routing.py`, `runtime_settings.py`, tests that mention
  `intent.active_mode`

### 2D-B files

- `backend/app/rag/query/control/breadth.py`
- `backend/app/rag/query/control/budget.py`
- `backend/app/rag/query/control/routing.py`
- `backend/app/rag/query/config.py`
- `backend/app/rag/query/planner.py`
- `backend/app/rag/query/diversify_context.py`
- `backend/app/rag/query/validate_citations.py`
- `backend/app/services/query_stats_service.py`
- eval/golden-set fixtures and tests that still contain `preferred_flavor=discovery`

### Tests To Add Or Rewrite

- `resolve_breadth("discovery")` maps to balanced with deprecation trace, or `QueryConfig` rejects it
  after the compatibility window.
- `VALID_BREADTHS == {"precise", "balanced", "broad"}`.
- `needs_discovery` drives broad prompt for non-multi scopes.
- `needs_discovery` budget behavior is explicit.
- `cfg.use_multi_hop=false` vetoes inferred discovery multi-hop.
- Existing `discovery` bypass tests are replaced by migration-delta tests.
- `retrieval_flavor=discovery` query-plan tests assert the chosen migration behavior, not the old
  profile.

---

## 7. Non-Goals

- No external `retrieval_flavor` -> `retrieval_breadth` API rename in this phase.
- No new keyword lists or deterministic keyword routing expansion.
- No per-dimension confidence.
- No `requested_format`.
- No removal of `exact`/`recall` legacy flavor names.

---

## 8. Recommendation

Proceed in this order:

1. Land 2D-A reporting cleanup now; it is non-behavioral and useful immediately.
2. Write a 2D-B implementation plan for discovery retirement, with the multi-hop default question
   answered explicitly.
3. Run the focused discovery eval before touching production routing code.
4. Only then remove the `discovery` breadth row and legacy behavior.

Do not delete the active-mode rollback or discovery breadth in the same commit.
