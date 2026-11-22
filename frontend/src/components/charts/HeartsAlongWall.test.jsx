import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import HeartsAlongWall from './HeartsAlongWall'

// 120 photos: the first 60 on one day, the rest weeks later; photo 70 is the busiest.
const photos = Array.from({ length: 120 }, (_, i) => ({
  number: i + 1,
  date: i < 60 ? '2023-07-30' : '2023-08-20',
  hearts: i === 69 ? 400 : 100 + (i % 7) * 10,
  writing: i === 69 ? 100 : 20 + (i % 5),
}))

const frame = () => screen.getByRole('group', { name: /Hearts along the wall/ })
const chart = () => screen.getByRole('img', { name: /Hearts counted along the wall/ })

describe('HeartsAlongWall', () => {
  it('names itself, its legend and its busiest stretch', () => {
    render(<HeartsAlongWall photos={photos} />)

    expect(screen.getByRole('heading', { name: 'Hearts along the wall' })).toBeInTheDocument()
    expect(screen.getByText('With writing')).toBeInTheDocument()
    expect(screen.getByText('No writing')).toBeInTheDocument()
    expect(chart()).toHaveAccessibleName(/photo 1 to 120/)
    // two photos to a column at this width: photos 69 and 70 (150 + 400 hearts) are the busiest
    expect(screen.getByText(/Busiest stretch: photos 69–70, 550 hearts\./)).toBeInTheDocument()
  })

  it('marks the two visits along the top', () => {
    render(<HeartsAlongWall photos={photos} />)

    expect(screen.getByText('30 Jul 2023')).toBeInTheDocument()
    expect(screen.getByText('20 Aug 2023')).toBeInTheDocument()
    // and the note names them too, so a narrow screen that has no room for the labels still says when
    expect(screen.getByText(/Photographed 30 Jul 2023 and 20 Aug 2023\./)).toBeInTheDocument()
  })

  it('draws a column for every stretch, thin enough to leave a gap between them', () => {
    const { container } = render(<HeartsAlongWall photos={photos} />)

    const columns = container.querySelectorAll('.viz-column')
    expect(columns.length).toBeGreaterThan(20)
    expect(columns.length).toBeLessThanOrEqual(photos.length)
    expect(container.querySelectorAll('.viz-fill-accent').length).toBeGreaterThan(0)
    expect(container.querySelectorAll('.viz-fill-context').length).toBeGreaterThan(0)
  })

  it('reads out the stretch under the pointer', () => {
    const { container } = render(<HeartsAlongWall photos={photos} />)
    const svg = container.querySelector('svg')
    svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: 760, height: 260 })

    expect(container.querySelector('.viz-tip')).toBeNull()
    fireEvent.pointerMove(svg, { clientX: 46 + 5 }) // the first columns
    const tip = container.querySelector('.viz-tip')
    expect(tip).toHaveTextContent(/Photos? 1/)
    expect(within(tip).getByText('With writing')).toBeInTheDocument()

    fireEvent.pointerLeave(svg)
    expect(container.querySelector('.viz-tip')).toBeNull()
  })

  it('can be read with the keyboard: arrow keys step along, Home and End jump to the ends', async () => {
    const user = userEvent.setup()
    const { container } = render(<HeartsAlongWall photos={photos} />)

    await user.click(document.body)
    await act(async () => frame().focus())
    await user.keyboard('{Home}')
    expect(container.querySelector('.viz-tip')).toHaveTextContent(/Photos? 1[–\d]*/)
    const firstText = container.querySelector('.viz-tip-title').textContent

    await user.keyboard('{ArrowRight}')
    expect(container.querySelector('.viz-tip-title').textContent).not.toBe(firstText)

    await user.keyboard('{ArrowLeft}{ArrowLeft}{ArrowLeft}')
    expect(container.querySelector('.viz-tip-title').textContent).toBe(firstText) // stops at the start

    await user.keyboard('{End}')
    expect(container.querySelector('.viz-tip-title').textContent).toMatch(/120$/)
    expect(screen.getByText(/with writing\.$/)).toBeInTheDocument() // the live region says it too

    await user.keyboard('{x}') // other keys do nothing
    expect(container.querySelector('.viz-tip-title').textContent).toMatch(/120$/)
  })

  it('starts the keyboard on the busiest stretch', async () => {
    const user = userEvent.setup()
    const { container } = render(<HeartsAlongWall photos={photos} />)

    await act(async () => frame().focus())
    // a first arrow press moves one stretch from the busiest (photos 69–70), so right then left lands back on it
    await user.keyboard('{ArrowRight}{ArrowLeft}')
    expect(container.querySelector('.viz-tip-title')).toHaveTextContent('Photos 69–70')
    expect(container.querySelector('.viz-tip-value')).toHaveTextContent('550 hearts')
  })

  it('has a table view with every value, and a way back to the chart', async () => {
    const user = userEvent.setup()
    render(<HeartsAlongWall photos={photos} />)

    await user.click(screen.getByRole('button', { name: 'View as table' }))
    const table = screen.getByRole('table')
    expect(within(table).getByRole('columnheader', { name: 'With writing' })).toBeInTheDocument()
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(1 + 3) // 120 photos in rows of 40
    expect(within(rows[1]).getByRole('rowheader')).toHaveTextContent('1–40')
    const totalHearts = photos.reduce((sum, p) => sum + p.hearts, 0)
    const shown = rows.slice(1).reduce((sum, row) => sum + Number(within(row).getAllByRole('cell')[0].textContent.replace(/\D/g, '')), 0)
    expect(shown).toBe(totalHearts)

    await user.click(screen.getByRole('button', { name: 'View as chart' }))
    expect(chart()).toBeInTheDocument()
  })

  it('draws nothing without photos', () => {
    const { container } = render(<HeartsAlongWall photos={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
})
