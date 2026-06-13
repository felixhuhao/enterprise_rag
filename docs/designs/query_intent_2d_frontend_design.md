# Query-Intent Routing 2D — Frontend Cleanup Design

**Status:** Draft. Follows the 2D-B backend retirement (`8257985`), which was backend-only.
**Depends on:** 2D-B discovery retirement (backend maps `retrieval_flavor=discovery → balanced` with a
deprecation trace; `query.use_multi_hop` versioned default flipped to `true`).

## Purpose

The 2D-B commit retired `discovery` as a retrieval breadth on the backend but touched no frontend.
Two UI surfaces are now stale:

1. `discovery` is still a **user-selectable** retrieval-flavor option in the Vue settings / eval /
   chat selectors, even though selecting it now silently behaves as `balanced`.
2. The settings form initializes/falls back `useMultiHop` to `false`, but the backend's versioned
   default is now `true`.

This is cleanup only — no API change. The external config field stays `retrieval_flavor` (the
`retrieval_flavor → retrieval_breadth` rename remains a separate, deferred migration).

## Decision: Option 1 — coerce on read, drop the selector option, keep the label

Chosen over "show a disabled deprecated option" (transitional code + a second cleanup pass for an
internal tool) and "hard-remove including labels" (would break rendering of historical
`query_run_stats` / eval rows that still carry `retrieval_flavor=discovery`).

The frontend does **not** need pervasive coercion, because the backend already maps any incoming
`discovery → balanced`. Coercion is only needed when a persisted `discovery` value is loaded into a
control whose selectable set has lost `discovery`: the settings form's `query.retrieval_flavor` read,
and the eval draft/case editor's `preferred_flavor` load.

### Contract — three lists, deliberately distinct

`FLAVOR_KEYS` today does **two** jobs: it is both the user-selectable set *and* the
display/iteration order for per-flavor summaries. Those must split:

- **Display/iteration order — keeps `discovery` (`FLAVOR_KEYS` unchanged).** Per-flavor summary
  tables iterate `FLAVOR_KEYS` (`QueryStatsCards` "按策略" rows, `EvalRunPanel` `per_flavor` rows).
  Historical aggregates can still contain a `discovery` bucket; dropping it here would *silently omit
  historical discovery metrics*. So `FLAVOR_KEYS` retains `discovery` and stays the display order.
- **Selectable set — loses `discovery` (new `SELECTABLE_FLAVOR_KEYS`).** Introduce
  `SELECTABLE_FLAVOR_KEYS = ['balanced','exact','recall']` and derive
  `FLAVOR_OPTIONS = SELECTABLE_FLAVOR_KEYS.map(...)`. Every user-facing picker consumes the selectable
  list (directly or via `FLAVOR_OPTIONS`), so none offers `discovery`.
- **Display label map — keeps `discovery`.** `flavorLabel` still resolves `discovery → 关联查找` so
  historical rows and the retained summary bucket render.
- **Two normalization points.** A small `normalizeFlavor(value)` helper maps `discovery → balanced`
  (and any unknown → `balanced`), applied wherever a **persisted** flavor is loaded into a control
  whose selectable set has lost `discovery`:
  1. **Settings load** — `query.retrieval_flavor` read in `SettingsView.vue`.
  2. **Eval draft/case editor load** — `preferred_flavor` copied into `draftForm` by
     `openDraftEditor` / `openGoldenCaseEditor` in `EvalRunPanel.vue`. An old case with
     `preferred_flavor: discovery` would otherwise leave the (now-`SELECTABLE_FLAVOR_KEYS`) editor
     buttons with no active choice and re-save the retired value.

  The chat debug config is a non-persisted `ref` defaulting to `balanced`, so it needs no coercion —
  only the option removed.

## Surfaces to change

`labelMaps.ts` becomes the home of the two-list split: `FLAVOR_KEYS` (display order, keeps
`discovery`) and the new `SELECTABLE_FLAVOR_KEYS` (no `discovery`), with
`FLAVOR_OPTIONS = SELECTABLE_FLAVOR_KEYS.map(...)`. Selectors that consume `FLAVOR_OPTIONS`
(chat / retrieval-test / stats-filter) update automatically; the consumers that reference
`FLAVOR_KEYS` **directly** must each be classified as display (keep `FLAVOR_KEYS`) or selectable
(switch to `SELECTABLE_FLAVOR_KEYS`).

| File | Change |
| --- | --- |
| `frontend/src/utils/labelMaps.ts` | **Primary edit.** Keep `FLAVOR_KEYS` (with `discovery`) as the display/order list. Add `SELECTABLE_FLAVOR_KEYS = ['balanced','exact','recall']`, derive `SelectableFlavorKey = typeof SELECTABLE_FLAVOR_KEYS[number]`, and change `FLAVOR_OPTIONS` to derive from `SELECTABLE_FLAVOR_KEYS`. **Keep** the `discovery` entry in the label/description maps used by `flavorLabel`. Add `normalizeFlavor(value): SelectableFlavorKey` (`discovery`/unknown → `balanced`). |
| `frontend/src/components/settings/StrategyTuningPanel.vue` | Hand edit: drop `discovery` from the `FlavorKey` type and the `['balanced','exact','recall','discovery']` literal arrays. |
| `frontend/src/components/settings/SettingsView.vue` | Hand edit: drop the `discovery` `strategyProfiles` tuning tab + `FlavorKey` type; **reattach the `multiHopMaxDiscovered` budget control to `flavors: ['balanced']`** (see below); `normalizeFlavor(...)` on the `query.retrieval_flavor` read; flip `useMultiHop` init + `readBool(..., 'query.use_multi_hop', …)` fallback `false` → `true`. |
| `frontend/src/components/evaluate/EvalRunPanel.vue` | Hand edit: the run-pills (`:57`) and draft-editor (`:348`) `v-for="mode in FLAVOR_KEYS"` are **selectable** controls → switch to `SELECTABLE_FLAVOR_KEYS` (and import it). Apply `normalizeFlavor(...)` to `preferred_flavor` in `openDraftEditor` (`:840`) and `openGoldenCaseEditor` (`:860`) so persisted `discovery` cases load as `balanced`. **Leave** the `flavorRows` `per_flavor` summary (`:555`) on `FLAVOR_KEYS` so historical discovery metrics still render. |
| `frontend/src/components/evaluate/QueryStatsCards.vue` | **No edit needed** — `flavorRows` (`:157`) is a display summary; it keeps `FLAVOR_KEYS` and thus keeps showing any historical `discovery` bucket. (Verify it renders.) |
| `QueryChatView.vue`, `RetrievalTestView.vue`, `QueryStatsRecords.vue` | **No edit needed** — they consume `FLAVOR_OPTIONS`, which now drops `discovery` automatically. (Verify each renders.) |

Display-only rendering (`RetrievalInfo.vue`, `QueryStatsRecords.vue` rows, eval tables) needs **no**
change — it renders via the retained `flavorLabel` map.

### Consequence to accept: the stats filter loses a `discovery` choice

`QueryStatsRecords.vue` uses `FLAVOR_OPTIONS` for its **filter** dropdown, so the dropdown no longer
offers "discovery" as a *filter* selection. Historical rows with `retrieval_flavor=discovery` still
**render** (label retained) and still appear in the per-flavor **summary** cards (those iterate
`FLAVOR_KEYS`, which keeps `discovery`) — you just can't filter-select by the retired flavor. This is
an accepted minor trade (YAGNI: filtering history by a retired flavor is rare). If
historical-by-discovery filtering is actually wanted, the stats filter would need its own option list
built from `FLAVOR_KEYS` rather than `FLAVOR_OPTIONS` — explicitly out of scope here unless requested.

## Relocate the multi-hop knob (do not orphan it)

The `multiHopMaxDiscovered` budget control (`query.multi_hop_max_discovered`, backend default `5`,
still live beside `use_multi_hop=True` in `config.py`) is today attached to `flavors: ['discovery']`
in `SettingsView.vue`'s `budgetControls`. Its **value is always persisted** (the save block writes
`query.multi_hop_max_discovered` unconditionally), but its **editing control only renders under the
active tab whose flavor matches** (`activeControls = budgetControls.filter(c => c.flavors.includes(activeFlavor))`).
Deleting the discovery tab would therefore make the knob uneditable — silently freezing it at the
loaded value — even though multi-hop now runs on the default `balanced` path.

Fix: change that control's `flavors` from `['discovery']` to `['balanced']`. Multi-hop discovery is
now a balanced-path behavior, so the balanced profile is its correct home. This is a one-line edit in
`budgetControls` and needs no save-logic change (the key is already written unconditionally).

## Multi-hop default alignment

`SettingsView.vue` currently does `useMultiHop: false` (form init) and
`readBool(data, 'query.use_multi_hop', false)` (load fallback). Both change to `true` so the form
reflects the backend's versioned default when the key is absent from the settings response. When the
key *is* present (the normal case, since `query.*` is seeded), the read already shows the true value;
this only fixes the absent-key fallback and the pre-load initial state.

## Out of scope (deferred / non-goals)

- **Surfacing `intent.inline_enabled` / `intent.active_mode` as admin UI kill switches.** They are
  backend/runtime-settings only today; adding UI toggles is a new feature, not cleanup. Rollback via
  the settings API already works without UI. Defer unless an in-UI kill switch is actually wanted.
- **External `retrieval_flavor → retrieval_breadth` API rename** — separate migration, per the 2D
  design non-goals.
- **Removing the `discovery` display label** — must stay for historical rows.

## Testing

The frontend has **no test runner today** (only `vue-tsc` type-checking + manual verification). This
cleanup adds a **minimal pure-unit Vitest** setup — `node` environment, no jsdom/`@vue/test-utils`,
no component mounting — and covers only the pure helpers in `labelMaps.ts`. Component-level behavior
is covered by type-checking (`vue-tsc -b`, which catches the list-split type breaks) plus the manual
checklist. This is a deliberately light precedent for an untested app; heavier component-mount testing
is out of scope for this cleanup.

**Automated (pure-unit Vitest):**

1. `normalizeFlavor('discovery') === 'balanced'`; `normalizeFlavor('balanced') === 'balanced'`;
   unknown → `'balanced'`; the other selectable flavors pass through; its return type is
   `SelectableFlavorKey`, not the display-order `FlavorKey`.
2. `SELECTABLE_FLAVOR_KEYS` does **not** contain `discovery`, and `FLAVOR_OPTIONS` (derived from it)
   has no `discovery` option; `FLAVOR_KEYS` **still** contains `discovery` (display-order guarantee).
3. `flavorLabel('discovery') === '关联查找'` (historical-render guarantee) and the label map still
   carries the `discovery` entry.

**Type-checked (`vue-tsc -b`) + manual:** the wiring changes — `SettingsView` `useMultiHop` default
and `query.retrieval_flavor` coercion, the `multiHopMaxDiscovered` relocation to the `balanced` tab,
the per-flavor summary still iterating `FLAVOR_KEYS`, and the eval-editor `preferred_flavor` coercion
— are guarded by the type system (the `SelectableFlavorKey` split makes a stale `discovery` literal a
compile error) and confirmed by the manual checklist below.

**Manual checklist:**

- The settings / eval / chat / retrieval-test flavor selectors no longer list discovery.
- A historical stats record with `retrieval_flavor=discovery` still renders `关联查找`, and a
  per-flavor summary still shows a `discovery` bucket when the data contains one.
- The `multiHopMaxDiscovered` slider is editable under the `balanced` tab; saving persists
  `query.multi_hop_max_discovered`.
- `useMultiHop` shows on (checked) by default; opening an old eval case with `preferred_flavor:
  discovery` shows `balanced` selected (no orphaned/blank button).
