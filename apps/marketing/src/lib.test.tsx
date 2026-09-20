// usePrefersReducedMotion must read the media query on first render and
// follow OS-level toggles through change events.
import { describe, it, expect, afterEach } from 'vitest'
import { render, cleanup, act } from '@testing-library/react'
import { usePrefersReducedMotion } from './lib'
import { reducedMotion } from './testSetup'

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
