# Query-Intent Routing 2C-3 — Trust-Gated Activation (the flip)

**Date:** 2026-06-13
**Status:** Spec — approved design, pending implementation plan.
**Roadmap:** `query_intent_routing_roadmap.md` → Stage 2C-3.
**Depends on:** 2C-1 (golden correctness, all gates green 2026-06-13), 2C-2 (inline shadow shipped,
601 green; production-shadow report + `activatable_diverged` audit available).

## Purpose

Make high-confidence inferred routes actually **drive** `query_plan` by versioning the activation
flags to `"true"`, gated on the 2C-1 correctness gates plus a 2C-3 offline eval go-gate. This is the
**first behavior change** in Design 2 — until now every stage was zero-delta or shadow-only. The
wiring already shipped in 2C-2; 2C-3 is the trust decision made permanent, with instant runtime
rollback. Answers *"should we let high-confidence routes actually drive?"*

> **Governing invariant (shared with Design 1/2):** Classify intent once. Apply user policy once.
> Derive execution once. Trace all three separately.

## Decisions locked during brainstorming

- **Acceptance gate = offline eval go-gate + lightweight post-flip watch.** The offline eval carries
  the weight (it is the *go* gate); the post-flip watch exists only to catch golden-set blind spots,
  with instant flag rollback as the action. Chosen over offline-only (no live regression trigger) and
  production-only (low-QPS feedback is slow/noisy and can't measure the one new risk — answer quality
  on flipped routes).
- **Flip form = versioned default + runtime override.** Flip the code `_DEFAULTS` to `"true"` so
  activation is in version control and reproducible; the `runtime_settings` value still wins, so an
  ops flip to `"false"` is instant rollback. Matches the trajectory where the classifier becomes the
  permanent path (2D removes the flags entirely).
- **Activation requires *both* flags.** `active_mode` only has teeth when `inline_enabled` is also on
  (the classifier must run to produce a route to drive). So 2C-3 versions **both** defaults to
  `"true"`; every production query then makes an inline classifier call by default — intended
  (full-traffic, per the 2C-2 decision).

## The activation fact

```
activate = intent.inline_enabled  AND  intent.active_mode
```

2C-2 left both code defaults `"false"` (dark launch; inline enabled operationally for shadow
gathering). 2C-3 versions both to `"true"`. With both on, `query_plan_node` emits the gated bundle,
which is the merged proposal **iff** `activatable(merged)` (high confidence and not a fallback) —
otherwise the deterministic bundle. Nothing about the gate logic changes; only the default flag
values do.

### Defaults vs. existing deployments (the precedence reality)

`get_cached(key)` returns `_cache.get(key, _DEFAULTS.get(key))` (`runtime_settings.py:79`) — the
DB-loaded `_cache` **wins** over `_DEFAULTS`. The DB seed only writes `query.*` keys
(`database.py:392`), so on a *fresh* install `intent.*` are absent from `_cache` and fall through to
`_DEFAULTS` — there, baking `"true"` activates them. But on the **current deployment** the 2C-2
dark-launch wrote an `intent.inline_enabled` row via the settings API, so `_cache` already holds
`intent.*` values that override the baked default. **Therefore:**

- Baking `_DEFAULTS = "true"` governs **fresh installs / missing keys only** — it makes activation the
  reproducible, version-controlled default.
- **Activating the existing deployment is an operational `runtime_settings` update** (set both keys
  `"true"` via the settings API), performed as the go-live step. This same lever is the rollback
  (set `"false"`).

So the go-live step has two parts that must both happen: (1) land the baked default (for fresh
installs + as the documented intent), and (2) update the running deployment's runtime settings. The
spec does **not** add a forced DB migration that overwrites existing rows — overwriting an operator's
explicit setting on deploy would be surprising and would fight the rollback lever; the runtime update
is deliberate and reversible.

## Acceptance: the offline eval go-gate

Run `backend/scripts/eval_golden_set.py` over `data/challenge_golden_set_v1.jsonl` as a **paired run**
— once `active-OFF` (baseline) and once `inline+active` ON — the same protocol `intent_2a` and
`control_model` used (see `data/intent_2a_*`, `data/control_model_*`).

**Enforceability prerequisite (a 2C-3 deliverable).** The leak check needs to know which cases the
classifier activated, but the current eval artifacts don't carry it: `run_retrieval_test()` returns
`query_plan` and a timing `trace`, not `routing_trace.inline_shadow`
(`retrieval_test_service.py:~92`), and full-eval traffic sets `is_eval=true` and is not persisted to
`query_run_stats` (`query_chat.py:~480`). So 2C-3 **surfaces `routing_trace` (incl. `inline_shadow`)
in the retrieval-test output** (the value is already in graph state from `query_plan_node`; it is
simply not returned). With that, a small paired-run comparator partitions cases into activatable vs
not and enforces the table below.

**Normalized comparison fields (Finding-3 fix).** "Identical" is defined over **behavior-bearing
fields only**, never raw bytes: ranked retrieval keys (chunk keys / doc IDs in order), `Hit@5`/`Hit@10`,
and the `query_plan` execution fields (the `decision_execution_dict` set: `use_hyde`,
`use_query_expansion`, `use_multi_hop`, `use_entity_fallback`, `budget_reason`, `prompt_variant`,
`answer_shape`, `steps`, plus the resolved `budget`). **Ignored:** timing, `trace`/`inline_shadow`
metadata, latency, and classifier telemetry — these differ whenever inline runs even when retrieval
behavior is unchanged, so comparing them would create false hard-stops.

| Check | Instrument | Gate |
| --- | --- | --- |
| **Leak check** (decisive) | paired `retrieval_only`, normalized fields per case, partitioned by `inline_shadow.activatable_diverged` | Every case whose normalized fields differ between OFF and ON **must** be in the activatable set. A non-activatable case that moves is a wiring leak — hard stop. |
| Retrieval non-regression | `retrieval_only` Hit@5/Hit@10, aggregate over activatable cases | No drop on the activatable cases. |
| Answer-quality non-regression | `full_judge` vs baseline | No net answer-quality regression; investigate every case-change (judge noise expected — confirm flips are improvements or neutral, never degradations). |
| Activatable audit | the 2C-2 report's `activatable_diverged` list + the paired-run activatable set | Each flipped route manually confirmed as wanted; re-confirm against the eval answers. |

The leak check is the cheap, decisive correctness signal: because the gate only activates
high-confidence cases, the set of queries whose normalized behavior changes must be a **subset** of
the activatable set. That catches any bundle/budget wiring bug for free.

The go-gate must pass **before** the defaults are baked. 2C-1 gates (already green) and the 2C-2
shadow report (`classifier_error_rate ≤ 1%`, `latency_ms p95 ≤ 6000`, volume ≥ 200, activatable
audit) are preconditions.

## Post-flip watch & rollback

**Watch (lightweight).** After baking the defaults, watch `classifier_error_rate` / `latency_ms` p95
via `report_inline_shadow.py` (it already reads these from `query_run_stats`), plus feedback if volume
permits. This catches golden-set blind spots, not the primary signal.

**Rollback (single action).** Set `intent.active_mode="false"` in `runtime_settings` (instant, no
deploy) → back to deterministic routes while the inline shadow keeps running for diagnosis. If the
inline *call itself* misbehaves (latency/errors), also set `intent.inline_enabled="false"`.

**Rollback triggers:** any hard-gate failure surfaced post-flip, an error/latency regression on real
traffic, or a confirmed answer-quality regression.

## Code deliverables

Small and contained — the heavy lifting was 2C-2.

1. **`backend/app/core/runtime_settings.py`** — flip both `_DEFAULTS` entries:
   ```python
   "intent.inline_enabled": "true",
   "intent.active_mode": "true",
   ```
2. **`backend/tests/conftest.py`** — autouse fixture pinning both flags `"false"` for the unit suite,
   so `query_plan_node` tests stay offline/deterministic unless they opt in:
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
   The 2C-2 inline/active tests set their flags *after* this fixture runs (via
   `monkeypatch.setitem`), so they still work; everything else is pinned deterministic.
3. **`backend/app/services/retrieval_test_service.py`** — surface the routing trace in the
   retrieval-test return dict (one line), so eval artifacts carry the activation evidence:
   ```python
   "routing_trace": state.get("routing_trace", {}),
   ```
   `routing_trace` (with `inline_shadow.activatable_diverged` and the proposal/det executions) is
   already produced by `query_plan_node` and sits in graph state; it is simply not currently returned.
4. **`backend/scripts/compare_activation_eval.py`** (new, standalone — archived after the flip like
   the other gate tools) — a paired-run comparator: takes the `active-OFF` and `inline+active-ON`
   retrieval-test result artifacts, compares the normalized behavior fields per case (ranked keys +
   `Hit@K` + `decision_execution_dict` + budget), partitions by `inline_shadow.activatable_diverged`,
   and asserts the changed set ⊆ the activatable set (the leak check). Pure aggregation function +
   thin file I/O, unit-tested like `aggregate_inline_shadow`.

**No changes** to the planner seam, `routing.py`, or the classifier — they are already correct from
2C-2. `build_query_plan` (used by `test_planner_characterization.py` and `get_query_plan`'s fallback)
never runs the inline seam, so characterization is unaffected by the default flip.

## Testing

1. **Activation regression (permanent protection).** With `inline+active` forced on (via
   `monkeypatch.setitem`, overriding the autouse fixture) and `classify_intent_inline` stubbed (no
   network): a high-confidence divergent intent **drives** the merged route + budget; a
   `fallback_used`/low-confidence proposal does **not** (stays deterministic). This promotes the 2C-2
   active-mode + fallback tests to "intended default behavior," guarding against silent regression
   after the flip.
2. **Shipped-default assertion.** One test that, with the autouse fixture temporarily lifted
   (`runtime_settings._cache` cleared of both keys so `get_cached` falls through to `_DEFAULTS`),
   asserts `runtime_settings.get_cached("intent.active_mode") == "true"` and
   `get_cached("intent.inline_enabled") == "true"` — so an accidental revert of the shipped default
   is caught.
3. **Comparator unit.** Feed the comparator synthetic paired result rows (one activatable case that
   changes, one non-activatable case that changes): assert it flags the non-activatable change as a
   leak and passes when only activatable cases move. Same pure-function pattern as the 2C-2
   `aggregate_inline_shadow` test.
4. **Suite stays green and offline.** Full unit suite passes with no network calls (the autouse
   fixture guarantees `query_plan_node` tests use the deterministic path unless they stub the
   classifier).

All real LLM stubbed in tests. The eval go-gate run is a manual operational step (like the 2C-1
scorer and 2C-2 dark-launch runs).

## Operational steps (manual, like 2C-1/2C-2)

1. Confirm preconditions: 2C-1 gates green, 2C-2 shadow report green + `activatable_diverged` audited.
2. Run the paired eval (`active-OFF` then `inline+active` ON) via `eval_golden_set.py` in
   `retrieval_only` and `full_judge`; run `compare_activation_eval.py` on the two artifacts and verify
   the go-gate table (leak check, non-regression, audit).
3. If green, land the code change (surface `routing_trace`, comparator, bake `_DEFAULTS` true + tests)
   and record the eval summary to a `data/` artifact + a closeout note (matching how
   2B/2C-1/control_model results were recorded).
4. **Activate the running deployment:** set `intent.inline_enabled="true"` and
   `intent.active_mode="true"` via the settings API / `runtime_settings.set` — the baked default only
   covers fresh installs; the existing DB rows win until updated.
5. Post-flip: run `report_inline_shadow.py` over the observation window; hold `intent.active_mode`
   ready for instant rollback (`"false"`).

## Out of scope (deferred)

- **Removing the flags / `_inline_intent` seam** — that is 2D, once activation "proves boring."
- **Discovery retirement** — 2D. Kept out so the router flip is the only behavior change in flight
  (clean blame trail).
- **Per-dimension confidence, continuous score, `requested_format`** — deferred per roadmap.
