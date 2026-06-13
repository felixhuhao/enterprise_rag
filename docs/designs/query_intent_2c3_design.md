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
  (the classifier must run to produce a route to drive). So 2C-3 versions **both** defaults to `"true"`.
- **Escalate only below-high (revised from 2C-2's full-traffic).** The inline classifier runs **only
  when `det.confidence != "high"`** — i.e. it escalates *medium/low* deterministic intent and **skips
  the LLM on deterministic-high cases**, which use the deterministic route directly. This restores the
  original 2B escalation intent ("it ran because deterministic was unsure"), which 2C-2's full-traffic
  simplification had drifted from. A 2C-3 dry run confirmed the cost of the drift: a slow remote model
  in a tight inline budget times out on a meaningful fraction of calls, and most of those calls were on
  cases the deterministic ladder already routes correctly. Trade-off (accepted): we forgo LLM
  *enrichment* on high cases (e.g. an extra marker the keyword matcher missed); 2C-1 showed the lift is
  concentrated below-high, so this is low-risk. No configurable per-bucket overrides (YAGNI) — if a
  `high` bucket ever needs the LLM, the honest fix is recalibrating the confidence ladder.
- **Hard safety gates vs soft lift/efficiency metrics.** For a *reversible, flag-gated* activation, the
  go-gate blocks only on **safety**: no route leak, no Hit@K regression, no confident-wrong activations
  (2C-1, green), the active-off fallback always yields the deterministic route, and inline latency p95
  bounded. Classifier timeout/error rate is **not** a blocker — a timeout falls back to the safe
  deterministic route — so it is reported as a lift/efficiency signal, not a gate. The volume gate is
  "enough representative cases to audit the activatable divergences" (curated golden set + a small live
  smoke window), not a fixed production-row count.

## The activation fact

```
activate = intent.inline_enabled  AND  intent.active_mode
```

2C-2 left both code defaults `"false"` (dark launch; inline enabled operationally for shadow
gathering). 2C-3 versions both to `"true"`. With both on, `query_plan_node` emits the gated bundle,
which is the merged proposal **iff** `activatable(merged)` (high confidence and not a fallback) —
otherwise the deterministic bundle. The trust-gate logic is unchanged; the default flag values flip.

### Escalation gate (the classifier runs only below-high)

```
run_inline = intent.inline_enabled  AND  det.confidence != "high"
```

`query_plan_node` calls the inline classifier **only when the deterministic intent is not already
high-confidence**. On a `det.confidence == "high"` case the classifier is skipped and the deterministic
bundle drives directly (which is `activatable` by definition, so it would have driven anyway). This
bounds the latency/cost blast radius to the escalated minority and is the structural fix for the
dry-run timeout findings. The skipped case records `inline_shadow = {"ran": false, "skip_reason":
"high_confidence"}` so the eval/report can distinguish "skipped because confident" from "skipped
because the flag is off" (`skip_reason: "inline_disabled"`). The deterministic confidence ladder is now
load-bearing for *when* to escalate; mis-calibration shows up in the divergence metrics and is tunable
there.

### Defaults vs. existing deployments (the precedence reality)

`get_cached(key)` returns `_cache.get(key, _DEFAULTS.get(key))` (`runtime_settings.py:79`) — the
DB-loaded `_cache` **wins** over `_DEFAULTS`. The seed loop currently inserts only `query.*` keys
(`database.py:391`, `if key.startswith("query."):`), so `intent.*` are not seeded as rows; on a
*fresh* DB they are absent from `_cache` and resolve to `_DEFAULTS` — there, baking `"true"` activates
them. But a deployment initialized/used **before 2C-3** may already hold explicit `intent.*` rows: the
2C-2 dark launch wrote `intent.inline_enabled` via the settings API, and a settings-save can persist
the full key set. Those rows win over the baked default. **Therefore:**

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

**Normalized comparison fields (Finding-3 fix, refined by the 2C-3 dry run).** "Identical" is defined
over **route-bearing fields** for the hard leak gate: the `query_plan` execution fields (the
`decision_execution_dict` set: `use_hyde`, `use_query_expansion`, `use_multi_hop`,
`use_entity_fallback`, `budget_reason`, `prompt_variant`, `answer_shape`, `steps`), fallback policy,
breadth/strict flags, and the resolved `budget`. `Hit@5`/`Hit@10` are a separate hard retrieval
non-regression gate. Ranked retrieval keys are reported as diagnostics, but not as hard leak evidence:
the 2C-3 paired dry run showed OFF-vs-OFF ranked-key churn with identical route/plan fields and no
Hit@K regression. **Ignored:** timing, `trace`/`inline_shadow` metadata, latency, and classifier
telemetry — these differ whenever inline runs even when retrieval behavior is unchanged, so comparing
them would create false hard-stops.

**Hard gates (safety — block the flip):**

| Check | Instrument | Gate |
| --- | --- | --- |
| **Leak check** (decisive) | paired `retrieval_only`, route-bearing normalized fields per case, partitioned by `inline_shadow.activatable_diverged` | Every case whose route-bearing fields differ between OFF and ON **must** be in the activatable set. A non-activatable route change is a wiring leak — hard stop. |
| Retrieval non-regression | `retrieval_only` Hit@5/Hit@10 | No Hit@5/Hit@10 drop. Ranked-key churn is diagnostic unless it causes a hit regression or route-bearing change. |
| Confident-wrong | 2C-1 `ambiguous_confident_wrong_count` | `== 0` (already green). |
| Answer-quality non-regression | `--mode full --judge` vs baseline | No net answer-quality regression; investigate every case-change (judge noise expected — confirm flips are improvements or neutral, never degradations). |
| Active-off fallback | activation regression test | With `active_mode` off (or a classifier failure), the emitted route is always the deterministic one. |
| Inline latency | escalated-call wall-clock p95 | `≤ 6000ms` (one classifier attempt; `max_retries=0`, `4s` request timeout). |
| Activatable audit | the 2C-2 report's `activatable_diverged` list + the paired-run activatable set | Each flipped route manually confirmed as wanted; re-confirm against the eval answers. |

The leak check is the cheap, decisive correctness signal: because the gate only activates
high-confidence cases, the set of queries whose route-bearing behavior changes must be a **subset**
of the activatable set. That catches any bundle/budget wiring bug without treating baseline retrieval
rank churn as an activation leak.

**Soft metrics (reported, inform tuning — do *not* block the flip):** classifier timeout/error rate,
fallback rate, and activatable-divergence rate. These are lift/efficiency signals: a timeout falls
back to the safe deterministic route, so a high timeout rate means "less LLM lift," not "unsafe."
Report them prominently — a catastrophic timeout rate is the "is activation even worth the latency?"
signal — but never gate on them. (The 2C-2 production-shadow report's `≤ 1%` error and `≥ 200` volume
thresholds were *operational* gates for that stage; they are **not** 2C-3 activation preconditions.)

The go-gate must pass **before** the defaults are baked. The only hard preconditions carried in are the
2C-1 gates (already green) and the `activatable_diverged` audit; everything else is measured by the
paired eval above.

**Inline timeout dry-run finding.** The inline path must stay under the 6000ms wall-clock p95 gate
for one classifier attempt. Provider/client retries multiply that envelope, so 2C-3 keeps the
offline/replay classifier tolerant but sets inline classifier retries to zero. A 6s request timeout
still produced >6s wall-clock p95 in the paired dry run, so the inline request timeout default is
4s, leaving client/provider overhead room while preserving deterministic fallback on slow calls.

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

Small and contained — the heavy lifting was 2C-2. **Split into two commits**, because the go-gate
*depends on* the eval tooling existing and must pass *before* the defaults are baked. Baking first
would mean running the gate against already-activated defaults — backwards.

### Commit 1 — eval-support tooling (defaults stay `"false"`)

1. **`backend/app/services/retrieval_test_service.py`** — surface the routing trace in the
   retrieval-test return dict (one line), so eval artifacts carry the activation evidence:
   ```python
   "routing_trace": state.get("routing_trace", {}),
   ```
   `routing_trace` (with `inline_shadow.activatable_diverged` and the proposal/det executions) is
   already produced by `query_plan_node` and sits in graph state; it is simply not currently returned.
2. **`backend/scripts/compare_activation_eval.py`** (new, standalone — archived after the flip like
   the other gate tools) — a paired-run comparator: takes the `active-OFF` and `inline+active-ON`
   retrieval-test result artifacts, compares route-bearing fields per case (`decision_execution_dict`
   + fallback policy + breadth/strict flags + budget), partitions by `inline_shadow.activatable_diverged`,
   and asserts the route-changed set ⊆ the activatable set (the leak check). It separately enforces no
   `Hit@K` regression and reports ranked-key changes as diagnostics. Pure aggregation function + thin
   file I/O, unit-tested like `aggregate_inline_shadow`.
3. **`backend/app/rag/query/control/llm_classifier.py` + `backend/app/config.py`** — keep the
   offline/replay classifier at one retry, run the inline classifier with `max_retries=0`, and set
   the inline request timeout default to `4s` so the wall-clock p95 gate has overhead room.
4. **`backend/app/rag/query/planner.py` + `backend/app/rag/query/control/routing.py`** — the
   **escalation gate**: `query_plan_node` calls the inline classifier only when
   `det.confidence != "high"`; high-confidence cases skip it and use the deterministic bundle.
   `inactive_inline_shadow(skip_reason)` records `"high_confidence"` vs `"inline_disabled"`. This is a
   change to the inline seam's *when-to-run* (not the gate logic), and it is inert while the flags are
   off — but it must land in Commit 1 so the go-gate eval measures the escalation-gated behavior that
   production will run.

With defaults still `"false"`, the paired eval is driven by **runtime overrides** (set the two
`runtime_settings` keys `"true"` for the ON run only). This commit changes no *default* behavior (the
flags stay off); it does change the inline seam's escalation condition, which only matters once a flag
is on.

The escalation gate makes the 2C-2 "high deterministic confidence + classifier failure" planner test
unreachable (high now skips the classifier), so that test is reframed to a below-high query; the
`activatable = high AND not fallback_used` guard remains unit-tested in `routing.py`'s tests.

### Commit 2 — bake activation (only if the go-gate is green)

4. **`backend/app/core/runtime_settings.py`** — flip both `_DEFAULTS` entries:
   ```python
   "intent.inline_enabled": "true",
   "intent.active_mode": "true",
   ```
5. **`backend/tests/conftest.py`** — autouse fixture pinning both flags `"false"` for the unit suite,
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
   `monkeypatch.setitem`), so they still work; everything else is pinned deterministic. This fixture
   must land **in the same commit** as the default flip, or the suite would start hitting the live LLM.

The planner seam, `routing.py`, and the classifier change only as described above (escalation gate +
inline budget, both in Commit 1). `build_query_plan` (used by `test_planner_characterization.py` and
`get_query_plan`'s fallback) never runs the inline seam, so characterization is unaffected by the
default flip.

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
2. **Land Commit 1** (routing-trace surfacing + comparator + comparator unit test); defaults stay
   `"false"`.
3. Run the paired eval with **runtime overrides** (defaults still false): `active-OFF` baseline, then
   set the two `runtime_settings` keys `"true"` and run `inline+active` ON — each via
   `eval_golden_set.py --mode retrieval_only` and `--mode full --judge`. Run
   `compare_activation_eval.py` on the two artifacts and verify the go-gate table (leak check,
   non-regression, audit). Reset the runtime overrides afterward.
4. If green, **land Commit 2** (bake `_DEFAULTS` true + the conftest autouse pin + the activation
   regression and shipped-default tests) and record the eval summary to a `data/` artifact + a
   closeout note (matching how 2B/2C-1/control_model results were recorded).
5. **Activate the running deployment:** set `intent.inline_enabled="true"` and
   `intent.active_mode="true"` via the settings API / `runtime_settings.set` — the baked default only
   covers fresh installs; the existing DB rows win until updated.
6. Post-flip: run `report_inline_shadow.py` over the observation window; hold `intent.active_mode`
   ready for instant rollback (`"false"`).

## Out of scope (deferred)

- **Removing the flags / `_inline_intent` seam** — that is 2D, once activation "proves boring."
- **Discovery retirement** — 2D. Kept out so the router flip is the only behavior change in flight
  (clean blame trail).
- **Per-dimension confidence, continuous score, `requested_format`** — deferred per roadmap.
