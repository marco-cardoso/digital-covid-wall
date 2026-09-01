import { useEffect, useState } from 'react'
import { fetchTributes } from '../api'

function NamesList() {
  const [tributes, setTributes] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const load = async () => {
      try {
        setTributes(await fetchTributes())
      } catch (err) {
        setError(err.message || 'Could not load the names.')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  return (
    <section className="names" aria-label="List of remembered names">
      <h2>The names</h2>
      <p className="section-hint">
        Everyone remembered on the wall. Each name carries a life, a family, a
        story.
      </p>

      {loading && <p className="status">Loading the names…</p>}
      {error && <p className="status status-error">{error}</p>}
      {!loading && !error && tributes.length === 0 && (
        <p className="status">No names have been added yet.</p>
      )}

      {tributes.length > 0 && (
        <ul className="name-list">
          {tributes.map((tribute) => (
            <li key={tribute.id} className="name-card">
              <div className="name-card-head">
                <span className="name-card-name">{tribute.name}</span>
                {tribute.years && (
                  <span className="name-card-years">{tribute.years}</span>
                )}
              </div>
              <p className="name-card-message">{tribute.message}</p>
              <p className="name-card-by">
                — {tribute.author}
                {tribute.relationship && `, ${tribute.relationship}`}
                {' · '}
                <span aria-label={`${tribute.candles} candles lit`}>
                  🕯 {tribute.candles}
                </span>
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export default NamesList
