import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchVictims } from '../api'
import Victims from './Victims'

vi.mock('../api')

describe('Victims (Honors)', () => {
  beforeEach(() => {
    fetchVictims.mockResolvedValue([
      { id: 1, name: 'Ada Lovelace' },
      { id: 2, name: 'Grace Hopper' },
    ])
  })

  it('lists the names that were read', async () => {
    render(<Victims />)

    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument()
    expect(screen.getByText('Grace Hopper')).toBeInTheDocument()
    expect(screen.getByText(/2 names read from the hearts/)).toBeInTheDocument()
  })

  it('puts each name on a line of its own, with a heart, and the full name on hover', async () => {
    fetchVictims.mockResolvedValue([{ id: 1, name: 'A very long name that will not fit on one line of a narrow screen' }])
    const { container } = render(<Victims />)

    const name = await screen.findByText(/A very long name/)
    expect(name).toHaveClass('victim-name')                      // CSS keeps it to one line, with an ellipsis
    expect(name).toHaveAttribute('title', 'A very long name that will not fit on one line of a narrow screen')
    const rows = container.querySelectorAll('li.victim-row')
    expect(rows).toHaveLength(1)
    expect(rows[0].querySelector('.victim-heart')).toHaveAttribute('aria-hidden', 'true')
  })

  it('says that not every name has been detected and some may have typos', async () => {
    render(<Victims />)
    await screen.findByText('Ada Lovelace')

    const notice = screen.getByLabelText('This site is under development')
    expect(notice).toHaveTextContent('Not every name has been detected yet')
    expect(notice).toHaveTextContent('typos')
  })

  it('links to the contact page from the notice', async () => {
    const onContact = vi.fn()
    render(<Victims onContact={onContact} />)

    await userEvent.click(screen.getByRole('button', { name: /Report a typo or a missing name/ }))
    expect(onContact).toHaveBeenCalledTimes(1)
  })

  it('has no link to follow when there is nowhere to send it', () => {
    render(<Victims />)
    expect(screen.queryByRole('button', { name: /Report a typo/ })).not.toBeInTheDocument()
  })

  it('searches the names', async () => {
    const user = userEvent.setup()
    render(<Victims />)

    await user.type(await screen.findByLabelText('Search names'), 'hopper')
    expect(screen.queryByText('Ada Lovelace')).not.toBeInTheDocument()
    expect(screen.getByText('Grace Hopper')).toBeInTheDocument()

    await user.clear(screen.getByLabelText('Search names'))
    await user.type(screen.getByLabelText('Search names'), 'zzz')
    expect(screen.getByText('No names match “zzz”.')).toBeInTheDocument()
  })

  it('says so when there are no names yet', async () => {
    fetchVictims.mockResolvedValue([])
    render(<Victims />)

    expect(await screen.findByText('No names have been added yet.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Search names')).not.toBeInTheDocument()
  })

  it('shows load errors, with a generic fallback', async () => {
    fetchVictims.mockRejectedValue(new Error('Names unavailable'))
    const { unmount } = render(<Victims />)
    expect(await screen.findByText('Names unavailable')).toBeInTheDocument()
    unmount()

    fetchVictims.mockRejectedValue(new Error(''))
    render(<Victims />)
    expect(await screen.findByText('Could not load the names.')).toBeInTheDocument()
  })
})
