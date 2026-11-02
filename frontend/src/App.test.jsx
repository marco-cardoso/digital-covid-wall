import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchStats, fetchTributes, fetchWallInfo } from './api'
import App from './App'

vi.mock('./api')
vi.mock('openseadragon', () => ({
  default: vi.fn(() => ({
    addHandler: vi.fn(),
    destroy: vi.fn(),
  })),
}))

describe('App', () => {
  beforeEach(() => {
    fetchWallInfo.mockResolvedValue({ dzi: '/wall/wall.dzi', width: 200000, height: 2000 })
    fetchTributes.mockResolvedValue([
      {
        id: 1,
        name: 'Elena Marchetti',
        years: '1948–2020',
        message: 'We still set a place for you.',
        author: 'Sofia',
        relationship: 'Granddaughter',
        candles: 12,
      },
    ])
    fetchStats.mockResolvedValue({ tributes: 3, candles: 57 })
  })

  it('renders the memorial heading and the panorama by default', async () => {
    render(<App />)

    expect(
      screen.getByRole('heading', { name: 'The Memorial Wall' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: 'Walk the wall' }),
    ).toBeInTheDocument()
    expect(await screen.findByTestId('wall-viewer')).toBeInTheDocument()
  })

  it('navigates to the names list', async () => {
    render(<App />)

    await userEvent.click(screen.getByRole('button', { name: 'The names' }))

    expect(
      screen.getByRole('heading', { name: 'The names' }),
    ).toBeInTheDocument()
    expect(await screen.findByText('Elena Marchetti')).toBeInTheDocument()
  })

  it('navigates to the dashboard', async () => {
    render(<App />)

    await userEvent.click(screen.getByRole('button', { name: 'Dashboard' }))

    expect(
      screen.getByRole('heading', { name: 'Dashboard' }),
    ).toBeInTheDocument()
    expect(await screen.findByText('Names remembered')).toBeInTheDocument()
  })

  it('renders the footer dedication', () => {
    render(<App />)

    expect(
      screen.getByText('Built in remembrance. Be gentle with one another.'),
    ).toBeInTheDocument()
  })
})
