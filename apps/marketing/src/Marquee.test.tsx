// The marquee's visual rows are decorative; the accessible content is the
// sr-only list. Both must carry the full question set.
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import Marquee from './Marquee'

describe('Marquee', () => {
  afterEach(cleanup)

  it('exposes every question once in an sr-only list and hides the scrolling rows', () => {
    const { container } = render(<Marquee />)
    const list = screen.getByRole('list')
    expect(list.className).toBe('sr-only')
    const items = screen.getAllByRole('listitem').map((li) => li.textContent)
    expect(items).toHaveLength(8)
    expect(new Set(items).size).toBe(8)
    expect(items).toContain('Did the steel quote come in?')

    const rows = container.querySelectorAll('.marquee')
    expect(rows).toHaveLength(2)
    rows.forEach((r) => expect(r.getAttribute('aria-hidden')).toBe('true'))
    expect(rows[0].className).not.toContain('marquee--reverse')
    expect(rows[1].className).toContain('marquee--reverse')
    // Each track holds the list twice so the -50% translate loops seamlessly.
    rows.forEach((r) => expect(r.querySelectorAll('.marquee__item')).toHaveLength(16))
  })
})
