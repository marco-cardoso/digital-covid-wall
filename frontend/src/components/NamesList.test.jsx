import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchTributes } from '../api'
import NamesList from './NamesList'

vi.mock('../api')

const tribute = {
  id: 1,
  name: 'Elena Marchetti',
  years: '1948–2020',
  message: 'We still set a place for you at the table.',
  author: 'Sofia',
  relationship: 'Granddaughter',
  candles: 12,
}

describe('NamesList', () => {
  beforeEach(() => {
    fetchTributes.mockResolvedValue([tribute])
  })

  it('renders each tribute with name, years, author, relationship and candles', async () => {
    render(<NamesList />)

    expect(await screen.findByText('Elena Marchetti')).toBeInTheDocument()
    expect(screen.getByText('1948–2020')).toBeInTheDocument()
    expect(
      screen.getByText('We still set a place for you at the table.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Sofia, Granddaughter/),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('12 candles lit')).toBeInTheDocument()
  })

  it('omits optional years and relationship when absent', async () => {
    fetchTributes.mockResolvedValue([
      { ...tribute, years: '', relationship: '' },
    ])
    render(<NamesList />)

    await screen.findByText('Elena Marchetti')
    expect(screen.queryByText('1948–2020')).not.toBeInTheDocument()
    expect(screen.queryByText(/, Granddaughter/)).not.toBeInTheDocument()
  })

  it('shows an empty message when there are no tributes', async () => {
    fetchTributes.mockResolvedValue([])
    render(<NamesList />)

    expect(
      await screen.findByText('No names have been added yet.'),
    ).toBeInTheDocument()
  })

  it('shows an error message when loading fails', async () => {
    fetchTributes.mockRejectedValue(new Error('Names unavailable'))
    render(<NamesList />)

    expect(await screen.findByText('Names unavailable')).toBeInTheDocument()
  })

  it('falls back to a generic error message', async () => {
    fetchTributes.mockRejectedValue(new Error())
    render(<NamesList />)

    expect(
      await screen.findByText('Could not load the names.'),
    ).toBeInTheDocument()
  })
})
