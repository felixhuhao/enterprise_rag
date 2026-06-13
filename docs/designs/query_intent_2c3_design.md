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

## Acceptance: the offline eval go-gate

Run `backend/scripts/eval_golden_set.py` over `data/challenge_golden_set_v1.jsonl` in both modes with
`inline+active` ON, compared against the logged `active-OFF` baseline — the same protocol
`intent_2a` and `control_model` used (see `data/intent_2a_*`, `data/control_model_*`).

| Check | Instrument | Gate |
| --- | --- | --- |
| **Leak check** (decisive) | `retrieval_only` Hit@5/Hit@10, per-case | **Non-activatable cases must be byte-identical to baseline.** Only `activatable_diverged` queries may move; any other per-case delta is a wiring leak, not intent — hard stop. |
| Retrieval non-regression | `retrieval_only` Hit@5/Hit@10, aggregate | No drop on the activatable cases. |
| Answer-quality non-regression | `full_judge` vs baseline | No net answer-quality regression; investigate every case-change (judge noise expected — confirm flips are improvements or neutral, never degradations). |
| Activatable audit | the 2C-2 report's `activatable_diverged` list | Each flipped route manually confirmed as wanted; re-confirm against the eval answers. |

The leak check is the cheap, decisive correctness signal: because the gate only activates
high-confidence cases, the set of queries whose retrieval changes must equal *exactly* the
activatable set — no more. That catches any bundle/budget wiring bug for free.

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
3. **Suite stays green and offline.** Full unit suite passes with no network calls (the autouse
   fixture guarantees `query_plan_node` tests use the deterministic path unless they stub the
   classifier).

All real LLM stubbed in tests. The eval go-gate run is a manual operational step (like the 2C-1
scorer and 2C-2 dark-launch runs).

## Operational steps (manual, like 2C-1/2C-2)

1. Confirm preconditions: 2C-1 gates green, 2C-2 shadow report green + `activatable_diverged` audited.
2. With `inline+active` ON in a staging/eval context, run `eval_golden_set.py` in `retrieval_only`
   and `full_judge`; verify the go-gate table (leak check, non-regression, audit).
3. If green, land the code change (bake `_DEFAULTS` true + tests) and record the eval summary to a
   `data/` artifact + a closeout note (matching how 2B/2C-1/control_model results were recorded).
4. Post-flip: run `report_inline_shadow.py` over the observation window; hold `intent.active_mode`
   ready for rollback.

## Out of scope (deferred)

- **Removing the flags / `_inline_intent` seam** — that is 2D, once activation "proves boring."
- **Discovery retirement** — 2D. Kept out so the router flip is the only behavior change in flight
  (clean blame trail).
- **Per-dimension confidence, continuous score, `requested_format`** — deferred per roadmap.
