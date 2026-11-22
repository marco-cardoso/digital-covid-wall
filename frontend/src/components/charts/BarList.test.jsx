import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import BarList from './BarList'

const items = [
  { label: 'Mum', value: 389, tip: '6.1% of the names read' },
  { label: 'Dad', value: 355, note: 'a second line' },
  { label: 'Friend', value: 50 },
]

describe('BarList', () => {
  it('lists every item with its value at the tip of the bar', () => {
    render(<BarList items={items} />)

    const rows = screen.getAllByRole('listitem')
    expect(rows).toHaveLength(3)
    expect(within(rows[0]).getAllByText('Mum')[0]).toBeInTheDocument()
    expect(within(rows[0]).getAllByText('389').length).toBeGreaterThan(0)
    expect(within(rows[1]).getByText('a second line')).toBeInTheDocument()
  })

  it('sizes the bars against the biggest value, or against `max` when given', () => {
    const { container, rerender } = render(<BarList items={items} />)
    const ratios = () => [...container.querySelectorAll('.bar-fill')].map((el) => Number(el.style.getPropertyValue('--ratio')))

    expect(ratios()[0]).toBe(1)
    expect(ratios()[2]).toBeCloseTo(50 / 389)

    rerender(<BarList items={items} max={1000} />)
    expect(ratios()[0]).toBeCloseTo(0.389)
  })

  it('never draws a bar longer than a full one', () => {
    const { container } = render(<BarList items={[{ label: 'Over', value: 20 }]} max={10} />)
    expect(Number(container.querySelector('.bar-fill').style.getPropertyValue('--ratio'))).toBe(1)
  })

  it('gives each row a readout that its row points to, so it works on focus too', () => {
    render(<BarList items={items} />)

    const [first] = screen.getAllByRole('listitem')
    expect(first).toHaveAttribute('tabindex', '0')
    const tip = document.getElementById(first.getAttribute('aria-describedby'))
    expect(tip).toHaveAttribute('role', 'tooltip')
    expect(tip).toHaveTextContent('Mum')
    expect(tip).toHaveTextContent('389')
    expect(tip).toHaveTextContent('6.1% of the names read')
  })

  it('uses a colour per item when one is given', () => {
    const { container } = render(
      <BarList items={[{ label: 'A', value: 1, color: 'rgb(1, 2, 3)' }, { label: 'B', value: 1 }]} />,
    )
    const [a, b] = container.querySelectorAll('.bar-fill')
    expect(a.style.background).toBe('rgb(1, 2, 3)')
    expect(b.style.background).toBe('var(--viz-accent)')
  })

  it('takes labels as text, never as markup', () => {
    const { container } = render(<BarList items={[{ label: '<img src=x onerror=alert(1)>', value: 3 }]} />)
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getAllByText('<img src=x onerror=alert(1)>').length).toBeGreaterThan(0)
  })
})
