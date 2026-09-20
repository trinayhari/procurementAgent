// css() turns one-off inline CSS strings into React style objects. It must
// camel-case ordinary properties, leave custom properties untouched, and
// shrug off the malformed input a hand-typed string will eventually contain.
import { describe, it, expect, afterEach } from 'vitest'
import { render, cleanup, act } from '@testing-library/react'
import { css, usePrefersReducedMotion } from './lib'
import { reducedMotion } from './testSetup'

describe('css()', () => {
  it('camel-cases hyphenated properties, trims whitespace, and leaves custom properties alone', () => {
    expect(css('display:flex; margin-top : 8px ;background-color:#fff')).toEqual({
      display: 'flex',
      marginTop: '8px',
      backgroundColor: '#fff',
    })
    expect(css('--chip:#2f8ce0;--fg-2: red')).toEqual({ '--chip': '#2f8ce0', '--fg-2': 'red' })
  })

  it('keeps colons inside values and returns {} for undefined, empty, or junk input', () => {
    expect(css('background:url(https://x.test/a.png);aspect-ratio:16 / 9')).toEqual({
      background: 'url(https://x.test/a.png)',
      aspectRatio: '16 / 9',
    })
    expect(css()).toEqual({})
    expect(css('')).toEqual({})
    expect(css(';;;')).toEqual({})
    expect(css('no-colon-here')).toEqual({})
    expect(css(':orphan-value;  : 12px')).toEqual({})
  })
})

describe('usePrefersReducedMotion', () => {
  afterEach(() => { cleanup(); reducedMotion(false) })

  function Probe() {
    return <span data-testid="p">{String(usePrefersReducedMotion())}</span>
  }

  it('reads the initial media query and follows change events', () => {
    reducedMotion(true)
    const { getByTestId } = render(<Probe />)
    expect(getByTestId('p').textContent).toBe('true')
    act(() => reducedMotion(false))
    expect(getByTestId('p').textContent).toBe('false')
    act(() => reducedMotion(true))
    expect(getByTestId('p').textContent).toBe('true')
  })
})
