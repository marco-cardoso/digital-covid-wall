import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchStats, fetchTributes, fetchVictims, fetchWallInfo } from './api'
import App from './App'

vi.mock('./api')
vi.mock('openseadragon', () => ({
  default: Object.assign(
    vi.fn(() => ({
      addHandler: vi.fn(),
      destroy: vi.fn(),
    })),
    { Rect: class {} },
  ),
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
    fetchVictims.mockResolvedValue([{ id: 1, name: 'Elena Marchetti' }])
    fetchStats.mockResolvedValue({ names: 6364, tributes: 3, candles: 57 })
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

  it('navigates to the Honors page', async () => {
    render(<App />)

    await userEvent.click(screen.getByRole('button', { name: 'Honors' }))

    // the list of names is held back for now
    expect(screen.getByRole('heading', { name: 'Coming soon' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Every name' })).not.toBeInTheDocument()
    expect(fetchVictims).not.toHaveBeenCalled()
  })

  it('navigates to the dashboard', async () => {
    render(<App />)

    await userEvent.click(screen.getByRole('button', { name: 'Dashboard' }))

    expect(
      screen.getByRole('heading', { name: 'Dashboard' }),
    ).toBeInTheDocument()
    expect(await screen.findByText('Names read from the wall')).toBeInTheDocument()
  })

  it('has a contact page, and says the site is in development on every page', async () => {
    const user = userEvent.setup()
    render(<App />)
    const pill = screen.getByRole('button', { name: /In development/ })
    expect(pill).toHaveTextContent('In development')        // in the header, so on the wall too

    await user.click(screen.getByRole('button', { name: 'Contact' }))
    expect(screen.getByRole('heading', { name: 'Contact' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Contact' })).toHaveAttribute('aria-current', 'page')

    await user.click(screen.getByRole('button', { name: 'The wall' }))
    await user.click(pill)
    expect(screen.getByRole('heading', { name: 'Contact' })).toBeInTheDocument()
  })

  it('renders the footer dedication, except over the full-screen wall', async () => {
    render(<App />)
    expect(screen.queryByText('Built in remembrance. Be gentle with one another.')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Honors' }))
    expect(
      screen.getByText('Built in remembrance. Be gentle with one another.'),
    ).toBeInTheDocument()
  })
})
