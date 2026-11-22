import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { sendFeedback } from '../api'
import Contact from './Contact'

vi.mock('../api')

describe('Contact', () => {
  beforeEach(() => {
    sendFeedback.mockResolvedValue({ ok: true })
  })

  it('says the site is under development and that not every name has been detected', () => {
    render(<Contact />)

    expect(screen.getByRole('heading', { name: 'Contact' })).toBeInTheDocument()
    expect(screen.getByText(/still under development/)).toBeInTheDocument()
    expect(screen.getByText(/not all of them have been detected/)).toBeInTheDocument()
    expect(screen.getByText(/some will contain typos/)).toBeInTheDocument()
    expect(screen.getByLabelText('This site is under development')).toBeInTheDocument()
  })

  it('will not send an empty message', async () => {
    const user = userEvent.setup()
    render(<Contact />)
    const send = screen.getByRole('button', { name: 'Send message' })

    expect(send).toBeDisabled()
    await user.type(screen.getByLabelText('Message'), '   ')
    expect(send).toBeDisabled()
    await user.type(screen.getByLabelText('Message'), 'Hello')
    expect(send).toBeEnabled()
  })

  it('sends what the visitor wrote, then thanks them', async () => {
    const user = userEvent.setup()
    render(<Contact />)

    await user.click(screen.getByLabelText('A name that’s missing'))
    await user.type(screen.getByLabelText(/^Name/), 'Ada Lovelace')
    await user.type(screen.getByLabelText('Message'), 'She is on the wall near the third panel.')
    await user.type(screen.getByLabelText(/Your email/), 'me@example.com')
    await user.click(screen.getByRole('button', { name: 'Send message' }))

    expect(sendFeedback).toHaveBeenCalledWith({
      kind: 'missing',
      name: 'Ada Lovelace',
      message: 'She is on the wall near the third panel.',
      contact: 'me@example.com',
      website: '',
    })
    expect(await screen.findByRole('status')).toHaveTextContent('Thank you')
    expect(screen.queryByRole('button', { name: 'Send message' })).not.toBeInTheDocument()
  })

  it('starts on typos, and changes what it asks for with the kind of message', async () => {
    const user = userEvent.setup()
    render(<Contact />)

    expect(screen.getByLabelText('A typo in a name')).toBeChecked()
    expect(screen.getByPlaceholderText('The name as it appears now')).toBeInTheDocument()

    await user.click(screen.getByLabelText('A name that’s missing'))
    expect(screen.getByPlaceholderText('The name that should be here')).toBeInTheDocument()

    await user.click(screen.getByLabelText('A suggestion'))
    expect(screen.queryByLabelText(/^Name/)).not.toBeInTheDocument()   // no name to give
    expect(screen.getByPlaceholderText('What would make this site better?')).toBeInTheDocument()

    await user.click(screen.getByLabelText('Something else'))
    expect(screen.getByPlaceholderText('What would you like to tell us?')).toBeInTheDocument()
  })

  it('sends a bot-trap field that people never fill in', async () => {
    const user = userEvent.setup()
    render(<Contact />)
    const trap = screen.getByLabelText('Leave this empty')
    expect(trap).toHaveValue('')
    expect(trap).toHaveAttribute('tabindex', '-1')

    await user.type(trap, 'http://spam.example')
    await user.type(screen.getByLabelText('Message'), 'Buy now')
    await user.click(screen.getByRole('button', { name: 'Send message' }))
    expect(sendFeedback).toHaveBeenCalledWith(expect.objectContaining({ website: 'http://spam.example' }))
  })

  it('shows what went wrong, keeps the message, and lets them try again', async () => {
    sendFeedback.mockRejectedValueOnce(new Error('Server is down'))
    const user = userEvent.setup()
    render(<Contact />)

    await user.type(screen.getByLabelText('Message'), 'A typo on the wall')
    await user.click(screen.getByRole('button', { name: 'Send message' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Server is down')
    expect(screen.getByLabelText('Message')).toHaveValue('A typo on the wall')

    await user.click(screen.getByRole('button', { name: 'Send message' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Thank you')
  })

  it('falls back to a generic reason when the error has no message', async () => {
    sendFeedback.mockRejectedValueOnce(new Error(''))
    const user = userEvent.setup()
    render(<Contact />)

    await user.type(screen.getByLabelText('Message'), 'Hi')
    await user.click(screen.getByRole('button', { name: 'Send message' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong.')
  })

  it('disables the button while sending', async () => {
    let finish
    sendFeedback.mockReturnValue(new Promise((resolve) => { finish = resolve }))
    const user = userEvent.setup()
    render(<Contact />)

    await user.type(screen.getByLabelText('Message'), 'Hi')
    await user.click(screen.getByRole('button', { name: 'Send message' }))
    expect(screen.getByRole('button', { name: 'Sending…' })).toBeDisabled()

    finish({ ok: true })
    await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument())
  })

  it('offers to send another, with a clean form', async () => {
    const user = userEvent.setup()
    render(<Contact />)

    await user.type(screen.getByLabelText(/^Name/), 'Someone')
    await user.type(screen.getByLabelText('Message'), 'First')
    await user.type(screen.getByLabelText(/Your email/), 'me@example.com')
    await user.click(screen.getByRole('button', { name: 'Send message' }))
    await user.click(await screen.findByRole('button', { name: 'Send another' }))

    expect(screen.getByLabelText('Message')).toHaveValue('')
    expect(screen.getByLabelText(/^Name/)).toHaveValue('')
    expect(screen.getByLabelText(/Your email/)).toHaveValue('me@example.com')   // kept: likely the same person
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
  })
})
