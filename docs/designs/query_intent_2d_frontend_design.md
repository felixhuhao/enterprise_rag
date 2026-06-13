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
`discovery → balanced`. The only place a persisted `discovery` value reaches a selector is the
settings form reading `query.retrieval_flavor`; that single read is normalized.

### Contract

- **Selectable flavor set loses `discovery`.** Remove `discovery` from the canonical selectable set
  and every selector/type derived from it.
- **Display label map keeps `discovery`.** Historical stats/eval rows still contain
  `retrieval_flavor=discovery`; the label (`关联查找` + its description) must continue to render.
  This is the deliberate split: *selectable set* ≠ *display map*.
- **One normalization point.** A small `normalizeFlavor(value)` helper maps `discovery → balanced`
  (and any unknown → `balanced`), applied where the settings form loads the persisted
  `query.retrieval_flavor`. The chat debug config is a non-persisted `ref` defaulting to `balanced`,
  so it needs no coercion — only the option removed.

## Surfaces to change

`FLAVOR_KEYS` in `labelMaps.ts` is the **single source of truth** for the selectable set:
`FLAVOR_OPTIONS = FLAVOR_KEYS.map(...)`, and the chat / retrieval-test / stats selectors all consume
`FLAVOR_OPTIONS` (or `FLAVOR_KEYS` directly). So most selector cleanup is **one edit** that cascades;
only the two settings components carry hardcoded `discovery` literals that must be edited by hand.

| File | Change |
| --- | --- |
| `frontend/src/utils/labelMaps.ts` | **Primary edit.** Remove `discovery` from `FLAVOR_KEYS` (cascades to `FLAVOR_OPTIONS` and all consumers below). **Keep** the `discovery` entry in the label/description maps used by `flavorLabel`. Add `normalizeFlavor(value): FlavorKey` (`discovery`/unknown → `balanced`). |
| `frontend/src/components/settings/StrategyTuningPanel.vue` | Hand edit: drop `discovery` from the `FlavorKey` type and the `['balanced','exact','recall','discovery']` literal arrays. |
| `frontend/src/components/settings/SettingsView.vue` | Hand edit: drop the `discovery` `strategyProfiles` tuning tab + `FlavorKey` type; **reattach the `multiHopMaxDiscovered` budget control to `flavors: ['balanced']`** (see below); `normalizeFlavor(...)` on the `query.retrieval_flavor` read; flip `useMultiHop` init + `readBool(..., 'query.use_multi_hop', …)` fallback `false` → `true`. |
| `QueryChatView.vue`, `RetrievalTestView.vue`, `QueryStatsCards.vue`, `EvalRunPanel.vue` | **No edit needed** — they derive options from `FLAVOR_KEYS`/`FLAVOR_OPTIONS` and update automatically once the primary edit lands. (Verify each renders correctly post-change.) |

Display-only rendering (`RetrievalInfo.vue`, `QueryStatsRecords.vue` rows, eval tables) needs **no**
change — it renders via the retained `flavorLabel` map.

### Consequence to accept: the stats filter loses a `discovery` choice

`QueryStatsRecords.vue` uses `FLAVOR_OPTIONS` for its **filter** dropdown, so dropping `discovery`
from `FLAVOR_KEYS` also removes "discovery" as a *filter* option. Historical rows with
`retrieval_flavor=discovery` still **render** (label retained) — you just can't filter-select by the
retired flavor. This is an accepted minor trade (YAGNI: filtering history by a retired flavor is rare,
and the rows remain visible). If historical-by-discovery filtering is actually wanted, the stats
filter would need its own option list that augments `FLAVOR_OPTIONS` with `discovery` — explicitly out
of scope here unless requested.

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

Frontend unit tests (Vitest, matching existing `frontend/src` test patterns):

1. `normalizeFlavor('discovery') === 'balanced'`; `normalizeFlavor('balanced') === 'balanced'`;
   unknown → `'balanced'`; the other valid flavors pass through.
2. The selectable `FLAVOR_KEYS` no longer contains `discovery`.
3. The display label map still resolves `discovery → '关联查找'` (historical-render guarantee).
4. `SettingsView` initializes `useMultiHop` to `true` and a settings response **without**
   `query.use_multi_hop` yields `useMultiHop === true`; a response with `"false"` yields `false`.
5. `SettingsView` loading `query.retrieval_flavor = "discovery"` shows `balanced` in the selector.
6. The `multiHopMaxDiscovered` budget control is reachable under the `balanced` tab (its
   `flavors` includes `'balanced'`) and `query.multi_hop_max_discovered` is still written on save.

Manual: confirm the settings/eval/chat flavor dropdowns no longer list discovery, and that a
historical stats record with `retrieval_flavor=discovery` still renders `关联查找`.
