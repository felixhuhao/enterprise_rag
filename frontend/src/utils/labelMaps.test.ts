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

  it('FLAVOR_OPTIONS has no discovery option', () => {
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

  it('returns the SelectableFlavorKey type', () => {
    const value: SelectableFlavorKey = normalizeFlavor('discovery')
    expect(value).toBe('balanced')
  })
})

describe('flavorLabel', () => {
  it('still resolves discovery for historical rows', () => {
    expect(flavorLabel('discovery')).toBe('关联查找')
    expect(FLAVOR_LABELS.discovery).toBe('关联查找')
  })
})
