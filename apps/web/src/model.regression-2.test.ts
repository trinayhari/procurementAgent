// Regression: ISSUE-002 — a numeric "Est. value" was stored verbatim, so a new
// project rendered "Value 1200000" next to every seeded project's "$4.2M".
// Found by /qa on 2026-08-10
// Report: .gstack/qa-reports/qa-report-localhost-2026-08-10.md
import { describe, it, expect } from 'vitest'
import { normaliseProjectValue } from './model'

describe('normaliseProjectValue', () => {
  it('formats the bare number that caused the bug', () => {
    expect(normaliseProjectValue('1200000')).toBe('$1.2M')
  })

  it('formats millions, dropping the decimal once it stops carrying signal', () => {
    expect(normaliseProjectValue('4200000')).toBe('$4.2M')
    expect(normaliseProjectValue('1000000')).toBe('$1M')
    expect(normaliseProjectValue('12000000')).toBe('$12M')
    expect(normaliseProjectValue('9500000')).toBe('$9.5M')
  })

  it('formats thousands and small amounts', () => {
    expect(normaliseProjectValue('45000')).toBe('$45K')
    expect(normaliseProjectValue('1000')).toBe('$1K')
    expect(normaliseProjectValue('750')).toBe('$750')
  })

  it('accepts the separators people actually type', () => {
    expect(normaliseProjectValue('1,200,000')).toBe('$1.2M')
    expect(normaliseProjectValue('$1200000')).toBe('$1.2M')
    expect(normaliseProjectValue(' 1200000 ')).toBe('$1.2M')
    expect(normaliseProjectValue('1200000.00')).toBe('$1.2M')
  })

  it('leaves already-formatted or non-numeric text exactly as typed', () => {
    expect(normaliseProjectValue('$4.2M')).toBe('$4.2M')
    expect(normaliseProjectValue('4.2M')).toBe('4.2M')
    expect(normaliseProjectValue('$850K')).toBe('$850K')
    expect(normaliseProjectValue('TBD')).toBe('TBD')
    expect(normaliseProjectValue('~$3M, pending award')).toBe('~$3M, pending award')
  })

  it('falls back to $0 for empty input, matching the placeholder', () => {
    expect(normaliseProjectValue('')).toBe('$0')
    expect(normaliseProjectValue('   ')).toBe('$0')
  })

  it('handles the boundaries between each unit', () => {
    expect(normaliseProjectValue('999')).toBe('$999')
    expect(normaliseProjectValue('999499')).toBe('$999K')
    // Never render "$1000K" for something that means $1M.
    expect(normaliseProjectValue('999999')).toBe('$1M')
    expect(normaliseProjectValue('0')).toBe('$0')
  })
})
