import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchInsights, fetchStats, fetchTributes } from '../api'
import Dashboard from './Dashboard'

vi.mock('../api')

const insights = {
  hearts: { total: 124408, with_writing: 26821, photos: 518 },
  per_photo: [
    { number: 1, date: '2023-07-30', hearts: 200, writing: 80 },
    { number: 2, date: '2023-07-30', hearts: 300, writing: 90 },
    { number: 3, date: '2023-08-20', hearts: 250, writing: 70 },
  ],
  messages: [
    { label: 'Love', count: 819 },
    { label: 'Miss you', count: 361 },
  ],
  relationships: [
    { label: 'Mum', count: 389 },
    { label: 'Dad', count: 355 },
  ],
}

describe('Dashboard', () => {
  beforeEach(() => {
    fetchStats.mockResolvedValue({ names: 6364, tributes: 3, candles: 57 })
    fetchTributes.mockResolvedValue([
      { id: 1, name: 'Elena Marchetti', candles: 12 },
      { id: 2, name: 'James Okafor', candles: 27 },
    ])
    fetchInsights.mockResolvedValue(insights)
  })

  it('renders the totals, average and most-remembered highlight', async () => {
    render(<Dashboard />)

    expect(await screen.findByText('Names read from the wall')).toBeInTheDocument()
    expect(screen.getAllByText((6364).toLocaleString()).length).toBeGreaterThan(0)
    expect(screen.getByText('Tributes')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('57')).toBeInTheDocument()
    // 57 / 3 = 19
    expect(screen.getByText('19')).toBeInTheDocument()
    expect(screen.getByText(/Most remembered:/)).toBeInTheDocument()
    expect(screen.getAllByText('James Okafor').length).toBeGreaterThan(0)
  })

  it('leads with the total of hearts counted on the wall', async () => {
    render(<Dashboard />)

    expect(await screen.findByText('hearts counted on the wall')).toBeInTheDocument()
    const hero = document.querySelector('.hero-value')
    expect(hero).toHaveTextContent((124408).toLocaleString())
    // it says how the number was got, and that it is a guide
    expect(screen.getByText(/Counted by computer across 518 photos/)).toBeInTheDocument()
    expect(screen.getByText(/not a census/)).toBeInTheDocument()
    // and the hearts that carry writing sit with the other totals
    const tiles = within(document.querySelector('.stat-grid'))
    expect(tiles.getByText('Hearts with writing')).toBeInTheDocument()
    expect(tiles.getByText((26821).toLocaleString())).toBeInTheDocument()
  })

  it('draws a chart for each kind of data we have', async () => {
    render(<Dashboard />)

    for (const title of [
      'Hearts along the wall',
      'From hearts to names',
      'Who they were to us',
      'What people wrote',
      'Candles by tribute',
    ]) {
      expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument()
    }
  })

  it('shows how the hearts narrow to names, with shares', async () => {
    render(<Dashboard />)

    const card = (await screen.findByRole('heading', { name: 'From hearts to names' })).closest('figure')
    expect(within(card).getAllByText('Hearts counted').length).toBeGreaterThan(0)
    expect(within(card).getByText('21.6% of hearts')).toBeInTheDocument()
    expect(within(card).getByText('23.7% of those')).toBeInTheDocument()
  })

  it('ranks who they were to us and what was written, each with its share of the names read', async () => {
    render(<Dashboard />)

    const who = (await screen.findByRole('heading', { name: 'Who they were to us' })).closest('figure')
    const rows = within(who).getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('Mum')
    expect(rows[0]).toHaveTextContent('389')
    expect(rows[0]).toHaveTextContent(`6.1% of the ${(6364).toLocaleString()} names read`)

    const wrote = screen.getByRole('heading', { name: 'What people wrote' }).closest('figure')
    expect(within(wrote).getAllByRole('listitem')[0]).toHaveTextContent('Love')
  })

  it('ranks the tributes by candles', async () => {
    render(<Dashboard />)

    const card = (await screen.findByRole('heading', { name: 'Candles by tribute' })).closest('figure')
    const rows = within(card).getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('James Okafor')
    expect(rows[0]).toHaveTextContent('27')
    expect(rows[0]).toHaveTextContent('47.4% of all candles lit')
    expect(rows[1]).toHaveTextContent('Elena Marchetti')
  })

  it('offers each chart as a table', async () => {
    const user = userEvent.setup()
    render(<Dashboard />)

    const card = (await screen.findByRole('heading', { name: 'Who they were to us' })).closest('figure')
    await user.click(within(card).getByRole('button', { name: 'View as table' }))
    const table = within(card).getByRole('table')
    expect(within(table).getByRole('columnheader', { name: 'Mentioned' })).toBeInTheDocument()
    expect(within(table).getByRole('rowheader', { name: 'Mum' })).toBeInTheDocument()
  })

  it('shows a zero average and no highlight when there are no tributes', async () => {
    fetchStats.mockResolvedValue({ names: 0, tributes: 0, candles: 0 })
    fetchTributes.mockResolvedValue([])
    render(<Dashboard />)

    await screen.findByText('Tributes')
    expect(screen.getByText('Candles per tribute')).toBeInTheDocument()
    expect(screen.queryByText(/Most remembered:/)).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Candles by tribute' })).not.toBeInTheDocument()
  })

  it('still shows the totals when the charts cannot be loaded', async () => {
    fetchInsights.mockRejectedValue(new Error('no insights'))
    render(<Dashboard />)

    expect(await screen.findByText('Names read from the wall')).toBeInTheDocument()
    expect(screen.queryByText('hearts counted on the wall')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Hearts along the wall' })).not.toBeInTheDocument()
    expect(screen.queryByText('Hearts with writing')).not.toBeInTheDocument()
    // the candles chart needs only the tributes, so it stays
    expect(screen.getByRole('heading', { name: 'Candles by tribute' })).toBeInTheDocument()
  })

  it('leaves out the hearts total when no hearts have been counted yet', async () => {
    fetchInsights.mockResolvedValue({ ...insights, hearts: { total: 0, with_writing: 0, photos: 0 }, per_photo: [] })
    render(<Dashboard />)

    await screen.findByText('Names read from the wall')
    expect(screen.queryByText('hearts counted on the wall')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Hearts along the wall' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'From hearts to names' })).not.toBeInTheDocument()
  })

  it('shows an error message when loading fails', async () => {
    fetchStats.mockRejectedValue(new Error('Stats unavailable'))
    render(<Dashboard />)

    expect(await screen.findByText('Stats unavailable')).toBeInTheDocument()
  })

  it('falls back to a generic error message', async () => {
    fetchStats.mockRejectedValue(new Error())
    render(<Dashboard />)

    expect(
      await screen.findByText('Could not load the statistics.'),
    ).toBeInTheDocument()
  })
})
