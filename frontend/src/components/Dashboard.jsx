import { useEffect, useState } from 'react'
import { fetchStats, fetchTributes } from '../api'

function Dashboard() {
  const [stats, setStats] = useState(null)
  const [tributes, setTributes] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const load = async () => {
      try {
        const [statsData, tributesData] = await Promise.all([
          fetchStats(),
          fetchTributes(),
        ])
        setStats(statsData)
        setTributes(tributesData)
      } catch (err) {
        setError(err.message || 'Could not load the statistics.')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const mostCandles = tributes.reduce(
    (best, t) => (t.candles > (best?.candles ?? -1) ? t : best),
    null,
  )
  const averageCandles =
    stats && stats.tributes > 0
      ? Math.round((stats.candles / stats.tributes) * 10) / 10
      : 0

  return (
    <section className="dashboard" aria-label="Memorial dashboard and statistics">
      <h2>Dashboard</h2>
      <p className="section-hint">
        A quiet accounting of what this community has built together.
      </p>

      {loading && <p className="status">Loading the statistics…</p>}
      {error && <p className="status status-error">{error}</p>}

      {!loading && !error && stats && (
        <>
          <div className="stat-grid">
            <div className="stat-card">
              <span className="stat-value">{stats.tributes}</span>
              <span className="stat-label">Names remembered</span>
            </div>
            <div className="stat-card">
              <span className="stat-value">{stats.candles}</span>
              <span className="stat-label">Candles lit</span>
            </div>
            <div className="stat-card">
              <span className="stat-value">{averageCandles}</span>
              <span className="stat-label">Candles per name</span>
            </div>
          </div>

          {mostCandles && (
            <p className="dashboard-highlight">
              Most remembered: <strong>{mostCandles.name}</strong> with{' '}
              {mostCandles.candles} candles.
            </p>
          )}
        </>
      )}
    </section>
  )
}

export default Dashboard
