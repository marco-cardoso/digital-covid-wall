import { useState } from 'react'
import { sendFeedback } from '../api'
import DevNotice from './DevNotice'

const KINDS = [
  { id: 'typo', label: 'A typo in a name', nameHint: 'The name as it appears now' },
  { id: 'missing', label: 'A name that’s missing', nameHint: 'The name that should be here' },
  { id: 'suggestion', label: 'A suggestion' },
  { id: 'other', label: 'Something else' },
]

const MAX_MESSAGE = 2000

const MESSAGE_PLACEHOLDERS = {
  typo: 'How it should read, and where you saw it. For example: “It says Marchettti; it should be Marchetti.”',
  missing: 'The name as written on the heart, and where on the wall it is if you know.',
  suggestion: 'What would make this site better?',
  other: 'What would you like to tell us?',
}

function Contact() {
  const [kind, setKind] = useState('typo')
  const [name, setName] = useState('')
  const [message, setMessage] = useState('')
  const [contact, setContact] = useState('')
  const [website, setWebsite] = useState('')       // hidden from people; bots fill it in
  const [status, setStatus] = useState('idle')     // idle | sending | sent | failed
  const [error, setError] = useState('')

  const current = KINDS.find((k) => k.id === kind)

  const submit = async (event) => {
    event.preventDefault()
    setStatus('sending')
    try {
      await sendFeedback({ kind, name, message, contact, website })
      setStatus('sent')
    } catch (err) {
      setError(err.message || 'Something went wrong.')
      setStatus('failed')
    }
  }

  const another = () => {
    setName('')
    setMessage('')
    setStatus('idle')
  }

  return (
    <section className="contact" aria-label="Contact">
      <p className="overline">Help us get it right</p>
      <h2>Contact</h2>
      <p className="lede">
        This website is still under development. The names were read from
        photographs of the wall, so not all of them have been detected yet and
        some will contain typos. Our goal is to make it as accurate as possible,
        and you can help: tell us about a mistake, a name we’ve missed, or
        anything you’d like to see.
      </p>

      {status === 'sent' ? (
        <div className="contact-thanks" role="status">
          <span className="contact-thanks-heart" aria-hidden="true" />
          <h3>Thank you</h3>
          <p>We’ve got your message, and every one helps make this a more accurate memorial.</p>
          <button type="button" className="contact-button contact-button-quiet" onClick={another}>
            Send another
          </button>
        </div>
      ) : (
        <form className="contact-form" onSubmit={submit}>
          <fieldset className="contact-kinds">
            <legend>What would you like to tell us?</legend>
            {KINDS.map((k) => (
              <label key={k.id} className={`contact-kind${kind === k.id ? ' contact-kind-on' : ''}`}>
                <input
                  type="radio"
                  name="kind"
                  value={k.id}
                  checked={kind === k.id}
                  onChange={() => setKind(k.id)}
                />
                {k.label}
              </label>
            ))}
          </fieldset>

          {current.nameHint && (
            <label className="contact-field">
              <span>Name <small>optional</small></span>
              <input
                type="text"
                value={name}
                maxLength={200}
                placeholder={current.nameHint}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
          )}

          <label className="contact-field">
            <span>Message</span>
            <textarea
              value={message}
              required
              rows={6}
              maxLength={MAX_MESSAGE}
              placeholder={MESSAGE_PLACEHOLDERS[kind]}
              onChange={(e) => setMessage(e.target.value)}
            />
          </label>

          <label className="contact-field">
            <span>Your email <small>optional, only if you’d like a reply</small></span>
            <input
              type="text"
              inputMode="email"
              autoComplete="email"
              value={contact}
              maxLength={200}
              onChange={(e) => setContact(e.target.value)}
            />
          </label>

          <div className="contact-trap" aria-hidden="true">
            <label>
              Leave this empty
              <input
                type="text"
                tabIndex={-1}
                autoComplete="off"
                value={website}
                onChange={(e) => setWebsite(e.target.value)}
              />
            </label>
          </div>

          {status === 'failed' && (
            <p className="status status-error" role="alert">
              We couldn’t send that: {error} Please try again.
            </p>
          )}

          <button type="submit" className="contact-button" disabled={status === 'sending' || !message.trim()}>
            {status === 'sending' ? 'Sending…' : 'Send message'}
          </button>
        </form>
      )}

      <DevNotice>
        Names are found automatically, so a few hearts may be skipped or misread.
        Searching the Honors page for a name you expected to see is a good way to
        check, and if it isn’t there, please tell us.
      </DevNotice>
    </section>
  )
}

export default Contact
