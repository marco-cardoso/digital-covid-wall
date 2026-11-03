import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchStats, fetchTributes } from '../api'
import Dashboard from './Dashboard'

vi.mock('../api')

describe('Dashboard', () => {
  beforeEach(() => {
    fetchStats.mockResolvedValue({ names: 6364, tributes: 3, candles: 57 })
    fetchTributes.mockResolvedValue([
      { id: 1, name: 'Elena Marchetti', candles: 12 },
      { id: 2, name: 'James Okafor', candles: 27 },
    ])
  })

  it('renders the totals, average and most-remembered highlight', async () => {
    render(<Dashboard />)

    expect(await screen.findByText('Names read from the wall')).toBeInTheDocument()
    expect(screen.getByText((6364).toLocaleString())).toBeInTheDocument()
    expect(screen.getByText('Tributes')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('57')).toBeInTheDocument()
    // 57 / 3 = 19
    expect(screen.getByText('19')).toBeInTheDocument()
    expect(screen.getByText(/Most remembered:/)).toBeInTheDocument()
    expect(screen.getByText('James Okafor')).toBeInTheDocument()
  })

  it('shows a zero average and no highlight when there are no tributes', async () => {
    fetchStats.mockResolvedValue({ names: 0, tributes: 0, candles: 0 })
    fetchTributes.mockResolvedValue([])
    render(<Dashboard />)

    await screen.findByText('Tributes')
    expect(screen.getByText('Candles per tribute')).toBeInTheDocument()
    expect(screen.queryByText(/Most remembered:/)).not.toBeInTheDocument()
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
