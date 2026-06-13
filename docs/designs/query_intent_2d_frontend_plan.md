# Query-Intent Routing 2D — Frontend Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the dead `discovery` retrieval-flavor option from the Vue settings/eval/chat selectors (backend already maps `discovery → balanced`), keep the discovery display label for historical rows, relocate the multi-hop knob so it stays editable, and align the `useMultiHop` form default with the backend's versioned `true`.

**Architecture:** Split `labelMaps.ts`'s `FLAVOR_KEYS` into two lists — `FLAVOR_KEYS` (display/iteration order, keeps `discovery`) and a new `SELECTABLE_FLAVOR_KEYS` (user-selectable, no `discovery`) with `FLAVOR_OPTIONS` derived from the selectable list. A `normalizeFlavor()` helper coerces persisted `discovery` at the two load points (settings form, eval editor). Components that consume `FLAVOR_OPTIONS` update automatically; the few that reference `FLAVOR_KEYS` directly are reclassified as display (keep) or selectable (switch). The type system (`vue-tsc`) catches stale `discovery` literals; a new minimal pure-unit Vitest setup guards the `labelMaps` helpers.

**Tech Stack:** Vue 3 + TypeScript, Vite 8, Arco Design Vue. New: Vitest 3 (pure-unit, `node` environment, no jsdom/`@vue/test-utils`).

**Spec:** `docs/designs/query_intent_2d_frontend_design.md`

---

## File Structure

| File | Responsibility | Change |
| --- | --- | --- |
| `frontend/package.json` | deps + scripts | Add `vitest` devDep + `"test": "vitest run"` script |
| `frontend/vitest.config.ts` | test config | New Vitest config (`node` env); keep production `vite.config.ts` unchanged |
| `frontend/src/utils/labelMaps.ts` | flavor lists, labels, `normalizeFlavor` | Primary edit — the two-list split + helper |
| `frontend/src/utils/labelMaps.test.ts` | pure-unit tests | New — covers the split + `normalizeFlavor` + label retention |
| `frontend/src/components/settings/SettingsView.vue` | settings form | Drop discovery tab/type, relocate multi-hop knob, coerce flavor read, flip `useMultiHop` default |
| `frontend/src/components/settings/StrategyTuningPanel.vue` | flavor tuning tabs | Drop `discovery` from local `FlavorKey` + tab-change allowlist |
| `frontend/src/components/evaluate/EvalRunPanel.vue` | eval run + editor | Switch selectable `v-for`s to `SELECTABLE_FLAVOR_KEYS`, coerce editor `preferred_flavor`; leave summary on `FLAVOR_KEYS` |

Components consuming `FLAVOR_OPTIONS` (`QueryChatView.vue`, `RetrievalTestView.vue`, `QueryStatsRecords.vue`) and the display summary in `QueryStatsCards.vue` need **no source edit** — verified in Task 5.

---

## Task 1: Vitest setup + `labelMaps.ts` two-list split

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/vitest.config.ts`
- Modify: `frontend/src/utils/labelMaps.ts:15-25`
- Test: `frontend/src/utils/labelMaps.test.ts` (create)

- [ ] **Step 1: Add Vitest dependency and test script**

Edit `frontend/package.json`. Add the `test` script and the `vitest` devDependency:

```json
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run"
  },
```

```json
  "devDependencies": {
    "@types/dompurify": "^3.0.5",
    "@types/node": "^24.12.3",
    "@vitejs/plugin-vue": "^6.0.6",
    "@vue/tsconfig": "^0.9.1",
    "typescript": "~6.0.2",
    "vite": "^8.0.12",
    "vitest": "^3.2.0",
    "vue-tsc": "^3.2.8"
  }
```

- [ ] **Step 2: Install the new dependency**

Run: `cd frontend && npm install`
Expected: `vitest` added to `node_modules`, `package-lock.json` updated, no errors.

- [ ] **Step 3: Add a dedicated Vitest config**

Create `frontend/vitest.config.ts`. Keep `frontend/vite.config.ts` unchanged; with the current Vite 8
stack, importing production `defineConfig` from `vitest/config` creates incompatible Vite/Rollup type
copies during `vue-tsc -b`.

```ts
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
```

- [ ] **Step 4: Write the failing tests**

Create `frontend/src/utils/labelMaps.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import {
  FLAVOR_KEYS,
  SELECTABLE_FLAVOR_KEYS,
  FLAVOR_OPTIONS,
  FLAVOR_LABELS,
  flavorLabel,
  normalizeFlavor,
  type SelectableFlavorKey,
} from './labelMaps'

describe('flavor lists', () => {
  it('SELECTABLE_FLAVOR_KEYS excludes discovery', () => {
    expect([...SELECTABLE_FLAVOR_KEYS]).toEqual(['balanced', 'exact', 'recall'])
    expect(SELECTABLE_FLAVOR_KEYS).not.toContain('discovery')
  })

  it('FLAVOR_OPTIONS (derived from selectable list) has no discovery option', () => {
    expect(FLAVOR_OPTIONS.map((o) => o.id)).not.toContain('discovery')
  })

  it('FLAVOR_KEYS still contains discovery for display order', () => {
    expect(FLAVOR_KEYS).toContain('discovery')
  })
})

describe('normalizeFlavor', () => {
  it('maps discovery to balanced', () => {
    expect(normalizeFlavor('discovery')).toBe('balanced')
  })

  it('passes through selectable flavors', () => {
    expect(normalizeFlavor('balanced')).toBe('balanced')
    expect(normalizeFlavor('exact')).toBe('exact')
    expect(normalizeFlavor('recall')).toBe('recall')
  })

  it('maps unknown/empty/null to balanced', () => {
    expect(normalizeFlavor('nonsense')).toBe('balanced')
    expect(normalizeFlavor('')).toBe('balanced')
    expect(normalizeFlavor(undefined)).toBe('balanced')
    expect(normalizeFlavor(null)).toBe('balanced')
  })

  it('returns the SelectableFlavorKey type (compile-time guard)', () => {
    // If normalizeFlavor's return type widened to include 'discovery',
    // this assignment would fail `vue-tsc -b`.
    const v: SelectableFlavorKey = normalizeFlavor('discovery')
    expect(v).toBe('balanced')
  })
})

describe('flavorLabel', () => {
  it('still resolves discovery for historical rows', () => {
    expect(flavorLabel('discovery')).toBe('关联查找')
    expect(FLAVOR_LABELS.discovery).toBe('关联查找')
  })
})
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `cd frontend && npm run test`
Expected: FAIL — `SELECTABLE_FLAVOR_KEYS`, `normalizeFlavor`, and the `SelectableFlavorKey` type are not exported yet (import/reference errors).

- [ ] **Step 6: Implement the two-list split in `labelMaps.ts`**

Replace lines 15-25 of `frontend/src/utils/labelMaps.ts` (the `FLAVOR_KEYS` / `FLAVOR_OPTIONS` / `flavorLabel` block). `FLAVOR_LABELS` (line 1-6) and `FLAVOR_DESCRIPTIONS` (line 8-13) keep their `discovery` entries unchanged. New block:

```ts
// Display / iteration order — KEEPS discovery so historical per-flavor
// summaries (QueryStatsCards, EvalRunPanel per_flavor) still render its bucket.
export const FLAVOR_KEYS = ['balanced', 'exact', 'recall', 'discovery'] as const

// User-selectable set — discovery retired (backend maps it to balanced).
export const SELECTABLE_FLAVOR_KEYS = ['balanced', 'exact', 'recall'] as const
export type SelectableFlavorKey = (typeof SELECTABLE_FLAVOR_KEYS)[number]

export const FLAVOR_OPTIONS = SELECTABLE_FLAVOR_KEYS.map((id) => ({
  id,
  name: FLAVOR_LABELS[id],
  desc: FLAVOR_DESCRIPTIONS[id],
}))

// Coerce a persisted flavor into the selectable set: retired `discovery`
// (and any unknown value) becomes `balanced`. Applied where a persisted value
// is loaded into a control whose selectable set no longer offers discovery.
export function normalizeFlavor(value: string | null | undefined): SelectableFlavorKey {
  return (SELECTABLE_FLAVOR_KEYS as readonly string[]).includes(value ?? '')
    ? (value as SelectableFlavorKey)
    : 'balanced'
}

export function flavorLabel(flavor: string): string {
  return FLAVOR_LABELS[flavor || 'balanced'] ?? flavor
}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd frontend && npm run test`
Expected: PASS — all tests in `labelMaps.test.ts` green.

- [ ] **Step 8: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts frontend/src/utils/labelMaps.ts frontend/src/utils/labelMaps.test.ts
git commit -m "feat(2D-fe): split flavor lists + add normalizeFlavor with pure-unit Vitest

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `SettingsView.vue` — drop discovery, relocate multi-hop knob, coerce, flip default

**Files:**
- Modify: `frontend/src/components/settings/SettingsView.vue` (lines 109-117 imports, 118, 192, 221-226, 229-236, 365, 386, 520-613)

This component has no unit test (component-level; covered by `vue-tsc` + manual checklist). The `SelectableFlavorKey` split makes any leftover `discovery` literal a compile error.

- [ ] **Step 1: Import `normalizeFlavor`**

`SettingsView.vue` does not currently import from `labelMaps`. Add an import alongside the other relative imports (after line 116, `import TokenSettingsPanel from './TokenSettingsPanel.vue'`):

```ts
import { normalizeFlavor } from '../../utils/labelMaps'
```

- [ ] **Step 2: Drop `discovery` from the local `FlavorKey` type**

Line 118:

```ts
type FlavorKey = 'balanced' | 'exact' | 'recall'
```

- [ ] **Step 3: Flip the `useMultiHop` form-init default**

Line 192, inside the `form` reactive object:

```ts
  useMultiHop: true,
```

- [ ] **Step 4: Remove the `discovery` strategy profile**

Delete the discovery entry from the `strategyProfiles` array (lines 221-226):

```ts
  {
    key: 'discovery',
    label: '关联查找',
    description: '多跳发现路径，先找相关实体，再围绕发现实体继续检索。',
    reason: 'discovery_current_path',
  },
```

After deletion, `strategyProfiles` ends with the `recall` entry (which closes with `},`).

- [ ] **Step 5: Relocate the multi-hop knob and drop discovery from budget-control flavors**

Replace the whole `budgetControls` array (lines 229-236) so no `flavors` list references `discovery`, and `multiHopMaxDiscovered` moves to the `balanced` tab:

```ts
const budgetControls: BudgetControl[] = [
  { key: 'searchLimit', label: '主检索候选', min: 1, max: 50, flavors: ['balanced'] },
  { key: 'hydeLimit', label: '语义扩展候选', min: 1, max: 50, flavors: ['balanced'] },
  { key: 'rrfMaxResults', label: '融合结果上限', min: 1, max: 50, flavors: ['balanced'] },
  { key: 'rerankMaxTopK', label: '重排/最终上下文上限', min: 1, max: 30, flavors: ['balanced'] },
  { key: 'queryExpansionCount', label: '扩展查询数量', min: 2, max: 4, flavors: ['recall'] },
  { key: 'multiHopMaxDiscovered', label: '多跳发现实体上限', min: 1, max: 10, flavors: ['balanced'] },
]
```

- [ ] **Step 6: Coerce the persisted `retrieval_flavor` on load**

Line 365, in `applySettings`:

```ts
  form.retrievalFlavor = normalizeFlavor(readString(data, 'query.retrieval_flavor', 'balanced'))
```

- [ ] **Step 7: Flip the `use_multi_hop` load fallback**

Line 386, in `applySettings`:

```ts
  form.useMultiHop = readBool(data, 'query.use_multi_hop', true)
```

- [ ] **Step 8: Remove discovery-only budget/capability branches**

Because the local `FlavorKey` no longer includes `discovery`, the old `if (flavor === 'discovery')`
branches in `buildBudget` and `buildCapabilities` are stale and must be removed.

In `buildBudget` (lines 543-553), delete the discovery branch entirely. The balanced/default branch
now covers the only editable balanced path and includes the relocated `multiHopMaxDiscovered` control
via the active controls list.

In `buildCapabilities` (lines 601-607), delete the discovery branch and include multi-hop in the
balanced/default capability list:

```ts
  return [
    ...common,
    { key: 'hyde', label: '语义扩展', enabled: Boolean(form.useHyde) },
    { key: 'multiHop', label: '多跳发现', enabled: Boolean(form.useMultiHop) },
    ...finishing,
  ]
```

Expected after this step: no `flavor === 'discovery'` checks remain in `SettingsView.vue`.

- [ ] **Step 9: Type-check**

Run: `cd frontend && npx vue-tsc -b`
Expected: PASS — no errors. (A leftover `discovery` literal anywhere typed `FlavorKey` would fail here.)

- [ ] **Step 10: Commit**

```bash
git add frontend/src/components/settings/SettingsView.vue
git commit -m "feat(2D-fe): retire discovery tab in settings, relocate multi-hop knob, align useMultiHop default

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `StrategyTuningPanel.vue` — drop discovery from type + tab allowlist

**Files:**
- Modify: `frontend/src/components/settings/StrategyTuningPanel.vue:87,129`

- [ ] **Step 1: Drop `discovery` from the local `FlavorKey` type**

Line 87:

```ts
type FlavorKey = 'balanced' | 'exact' | 'recall'
```

- [ ] **Step 2: Drop `discovery` from the tab-change allowlist**

Line 129, in `onFlavorTabChange`:

```ts
  if (['balanced', 'exact', 'recall'].includes(String(key))) {
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx vue-tsc -b`
Expected: PASS — no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/settings/StrategyTuningPanel.vue
git commit -m "feat(2D-fe): drop discovery from StrategyTuningPanel type + tab allowlist

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `EvalRunPanel.vue` — selectable lists + editor coercion (keep summary)

**Files:**
- Modify: `frontend/src/components/evaluate/EvalRunPanel.vue` (line 443 import, 57, 348, 834-848 `openDraftEditor`, 854-862 `openGoldenCaseEditor`; line 555 `flavorRows` left unchanged)

- [ ] **Step 1: Extend the labelMaps import**

Line 443:

```ts
import { FLAVOR_KEYS, SELECTABLE_FLAVOR_KEYS, flavorLabel, normalizeFlavor } from '../../utils/labelMaps'
```

`FLAVOR_KEYS` stays imported because the `flavorRows` per-flavor summary (line 555) still iterates it.

- [ ] **Step 2: Switch the run-flavor pills to the selectable list**

Line 57 (`v-for` for the run pills):

```html
              v-for="mode in SELECTABLE_FLAVOR_KEYS"
```

- [ ] **Step 3: Switch the draft-editor flavor buttons to the selectable list**

Line 348 (`v-for` inside the draft/case editor):

```html
                  v-for="mode in SELECTABLE_FLAVOR_KEYS"
```

- [ ] **Step 4: Coerce `preferred_flavor` when opening a draft**

In `openDraftEditor` (line 840), change the `preferred_flavor` assignment inside the `draftForm.value = { ... }` object:

```ts
    preferred_flavor: normalizeFlavor(draft.preferred_flavor),
```

- [ ] **Step 5: Coerce `preferred_flavor` when opening a golden case**

In `openGoldenCaseEditor` (line 860), change the `preferred_flavor` assignment inside the `draftForm.value = { ... }` object:

```ts
    preferred_flavor: normalizeFlavor(item.preferred_flavor),
```

- [ ] **Step 6: Confirm the summary still uses `FLAVOR_KEYS`**

Verify line 555 (`flavorRows` computed) is **unchanged** and still reads `return FLAVOR_KEYS` — this is the display-iteration path that must keep `discovery` so historical `per_flavor` buckets render.

Run: `cd frontend && grep -n "FLAVOR_KEYS\|SELECTABLE_FLAVOR_KEYS" src/components/evaluate/EvalRunPanel.vue`
Expected: `SELECTABLE_FLAVOR_KEYS` on lines 57 and 348; `FLAVOR_KEYS` on the import line (443) and the `flavorRows` computed (~555).

- [ ] **Step 7: Type-check**

Run: `cd frontend && npx vue-tsc -b`
Expected: PASS — no errors. (`runFlavor` and `draftForm.preferred_flavor` are string-typed, so comparing/assigning a `SelectableFlavorKey` from the `v-for` is valid.)

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/evaluate/EvalRunPanel.vue
git commit -m "feat(2D-fe): eval selectors use SELECTABLE_FLAVOR_KEYS, coerce editor preferred_flavor

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Full verification (auto-cascade consumers + build + manual checklist)

**Files:** none modified — verification only.

- [ ] **Step 1: Confirm cascade consumers need no edit**

Run: `cd frontend && grep -rn "FLAVOR_KEYS\|FLAVOR_OPTIONS" src/components/query-chat/QueryChatView.vue src/components/retrieval-test/RetrievalTestView.vue src/components/evaluate/QueryStatsRecords.vue src/components/evaluate/QueryStatsCards.vue`
Expected:
- `QueryChatView.vue` / `RetrievalTestView.vue` / `QueryStatsRecords.vue` reference `FLAVOR_OPTIONS` only (now discovery-free automatically).
- `QueryStatsCards.vue` references `FLAVOR_KEYS` in its `flavorRows` display summary (kept on purpose — retains discovery bucket).

- [ ] **Step 2: Run the full unit-test suite**

Run: `cd frontend && npm run test`
Expected: PASS — `labelMaps.test.ts` green.

- [ ] **Step 3: Full type-check + production build**

Run: `cd frontend && npm run build`
Expected: PASS — `vue-tsc -b` clean, `vite build` succeeds with no errors.

- [ ] **Step 4: Manual verification (dev server)**

Run: `cd frontend && npm run dev`, then in the browser confirm:
- The settings / eval-run / chat / retrieval-test flavor selectors no longer list 关联查找 (discovery).
- The `多跳发现实体上限` (multiHopMaxDiscovered) slider is visible and editable under the **标准问答 (balanced)** tab; saving persists `query.multi_hop_max_discovered`.
- `useMultiHop` shows enabled by default.
- Opening an existing eval case whose `preferred_flavor` was `discovery` shows **标准问答 (balanced)** selected (a real button is active, none blank).
- A historical query-stats record / eval `per_flavor` row with `retrieval_flavor=discovery` still renders the `关联查找` label.

- [ ] **Step 5: Final commit (only if verification produced a known file change)**

```bash
git add <specific changed file(s)>
git commit -m "chore(2D-fe): verification pass for discovery frontend retirement

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

(If nothing changed in this step, skip the commit. Do not use `git add -A` for the verification pass;
it can accidentally sweep unrelated local work into the commit.)
