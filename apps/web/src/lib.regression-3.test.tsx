// Regression: ISSUE-003 — a `border-color:…` hover on top of a
// `border:1px solid …` base dropped borderColor on un-hover while border stayed
// set, so React logged a shorthand/longhand styling-bug warning to the console
// on every hover pass over a project card or icon button.
// Found by /qa on 2026-08-10
// Report: .gstack/qa-reports/qa-report-localhost-2026-08-10.md
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { Box } from './lib'

afterEach(cleanup)

// The exact style pairing used by the Projects card (App.tsx) and the project
// Delete button — a shorthand base with a longhand hover override.
const BASE = 'background:var(--panel);border:1px solid var(--border);border-radius:16px'
const HOVER = 'border-color:var(--border-strong)'

function borderKeys(el: HTMLElement) {
  const s = el.style
  return {
    border: s.border,
    borderColor: s.borderColor,
    borderWidth: s.borderWidth,
    borderStyle: s.borderStyle,
  }
}

describe('Box border shorthand + hover borderColor', () => {
  it('keeps the same border keys set before, during and after hover', () => {
    render(<Box as="button" css={BASE} hover={HOVER}>Card</Box>)
    const el = screen.getByRole('button')

    const idle = borderKeys(el)
    fireEvent.mouseEnter(el)
    const hovered = borderKeys(el)
    fireEvent.mouseLeave(el)
    const after = borderKeys(el)

    // The bug: borderColor was present while hovered and gone afterwards, with
    // the `border` shorthand set the whole time — what React warns about.
    expect(Object.keys(idle).filter((k) => idle[k as keyof typeof idle])).toEqual(
      Object.keys(hovered).filter((k) => hovered[k as keyof typeof hovered]),
    )
    expect(idle).toEqual(after)
    expect(idle.borderColor).toBeTruthy()
    expect(idle.border).toBeFalsy()
  })

  it('applies the hover colour and restores the base colour on leave', () => {
    render(<Box as="button" css={BASE} hover={HOVER}>Card</Box>)
    const el = screen.getByRole('button')

    expect(el.style.borderColor).toBe('var(--border)')
    fireEvent.mouseEnter(el)
    expect(el.style.borderColor).toBe('var(--border-strong)')
    fireEvent.mouseLeave(el)
    expect(el.style.borderColor).toBe('var(--border)')
    // Width and style survive the shorthand being expanded.
    expect(el.style.borderWidth).toBe('1px')
    expect(el.style.borderStyle).toBe('solid')
  })

  // `el.style.borderWidth` is populated by the CSSOM whenever the shorthand is
  // set, so it can't tell the two cases apart. `el.style.border` can: it stays
  // set when the shorthand is left alone, and reads empty once the longhands are
  // written separately with a var() colour the CSSOM can't recombine.
  it('leaves the shorthand alone when the hover does not touch borderColor', () => {
    render(<Box as="button" css={BASE} hover="background:var(--panel-2)">Card</Box>)
    // Still a shorthand (happy-dom drops the var() when serialising it); the
    // split case leaves `border` empty, which is what test 1 asserts.
    expect(screen.getByRole('button').style.border).toBeTruthy()
  })

  it('leaves an unsplittable shorthand alone rather than mangling it', () => {
    render(<Box as="button" css="border:none" hover={HOVER}>Card</Box>)
    // 'none' is one token, not width/style/colour — must not be split.
    expect(screen.getByRole('button').style.border).toBeTruthy()
  })
})
