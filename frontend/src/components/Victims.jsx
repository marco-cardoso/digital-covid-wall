import { useEffect, useMemo, useState } from 'react'
import { fetchVictims } from '../api'

function Victims() {
  const [victims, setVictims] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')

  useEffect(() => {
    const load = async () => {
      try {
        setVictims(await fetchVictims())
      } catch (err) {
        setError(err.message || 'Could not load the names.')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase()
    if (!term) return victims
    return victims.filter((v) => v.name.toLowerCase().includes(term))
  }, [victims, query])

  return (
    <section className="victims" aria-label="Names read from the wall">
      <h2>Every name</h2>
      <p className="section-hint">
        {victims.length.toLocaleString()} names read from the hearts on the
        National Covid Memorial Wall.
      </p>

      {!loading && !error && victims.length > 0 && (
        <input
          type="search"
          className="victim-search"
          placeholder="Search names…"
          aria-label="Search names"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      )}

      {loading && <p className="status">Loading the names…</p>}
      {error && <p className="status status-error">{error}</p>}
      {!loading && !error && victims.length === 0 && (
        <p className="status">No names have been added yet.</p>
      )}
      {!loading && !error && victims.length > 0 && filtered.length === 0 && (
        <p className="status">No names match “{query}”.</p>
      )}

      {filtered.length > 0 && (
        <ul className="victim-list">
          {filtered.map((victim) => (
            <li key={victim.id} className="victim-chip">
              {victim.name}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export default Victims
