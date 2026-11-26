import { useEffect, useState } from 'react'
import { fetchInsights, fetchStats, fetchTributes } from '../api'
import BarList from './charts/BarList'
import ChartCard from './charts/ChartCard'
import HeartsAlongWall from './charts/HeartsAlongWall'
import { percentText } from './charts/chartMath'

// The charts are an extra: if the insights cannot be loaded the totals and tributes still show.
async function loadInsights() {
  try {
    return (await fetchInsights()) ?? null
  } catch {
    return null
  }
}

const CANDLE_BARS = 8

function Dashboard() {
  const [stats, setStats] = useState(null)
  const [tributes, setTributes] = useState([])
  const [insights, setInsights] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const load = async () => {
      try {
        const [statsData, tributesData, insightsData] = await Promise.all([
          fetchStats(),
          fetchTributes(),
          loadInsights(),
        ])
        setStats(statsData)
        setTributes(tributesData)
        setInsights(insightsData)
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

  const hearts = insights?.hearts?.total > 0 ? insights.hearts : null
  const names = stats?.names ?? 0

  // Every heart, the ones with writing, and the names read from them so far.
  const funnel = hearts && [
    { label: 'Hearts counted', value: hearts.total, note: `in ${hearts.photos.toLocaleString()} photos`, color: 'var(--viz-ramp-1)' },
    {
      label: 'Hearts with writing',
      value: hearts.with_writing,
      note: `${percentText(hearts.with_writing, hearts.total)} of hearts`,
      color: 'var(--viz-ramp-2)',
    },
    {
      label: 'Names read so far',
      value: names,
      note: `${percentText(names, hearts.with_writing)} of those`,
      color: 'var(--viz-ramp-3)',
    },
  ]

  const mentions = (list) =>
    list.map((m) => ({
      label: m.label,
      value: m.count,
      tip: `${percentText(m.count, names)} of the ${names.toLocaleString()} names read`,
    }))
  const mentionTable = (list, column) => ({
    columns: [column, 'Hearts'],
    rows: list.map((m) => [m.label, m.count]),
  })

  const candleTributes = [...tributes].sort((a, b) => b.candles - a.candles).slice(0, CANDLE_BARS)

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
          {hearts && (
            <div className="hero">
              <span className="hero-heart" aria-hidden="true" />
              <p className="hero-value">{hearts.total.toLocaleString()}</p>
              <p className="hero-label">hearts counted on the wall</p>
              <p className="hero-note">
                Counted by computer across {hearts.photos.toLocaleString()} photos. Where neighbouring photos
                overlap a heart can be counted twice, and some are missed, so it is a close guide, not a census.
              </p>
            </div>
          )}

          <div className="stat-grid">
            {hearts && (
              <div className="stat-card">
                <span className="stat-value">{hearts.with_writing.toLocaleString()}</span>
                <span className="stat-label">Hearts with writing</span>
              </div>
            )}
            <div className="stat-card">
              <span className="stat-value">{stats.names.toLocaleString()}</span>
              <span className="stat-label">Names read from the wall</span>
            </div>
          </div>

          {mostCandles && (
            <p className="dashboard-highlight">
              Most remembered: <strong>{mostCandles.name}</strong> with{' '}
              {mostCandles.candles} candles.
            </p>
          )}

          {(insights?.per_photo?.length > 0 || candleTributes.length > 0) && (
            <div className="chart-grid">
              {insights?.per_photo?.length > 0 && <HeartsAlongWall photos={insights.per_photo} />}

              {funnel && (
                <ChartCard
                  wide
                  title="From hearts to names"
                  subtitle="Names are read by computer from the writing on each heart, so this is a rough guide to how far the reading has got."
                  table={{
                    columns: ['Stage', 'Count'],
                    rows: funnel.map((step) => [step.label, step.value]),
                  }}
                >
                  <BarList items={funnel} max={hearts.total} />
                </ChartCard>
              )}

              {insights?.relationships?.length > 0 && (
                <ChartCard
                  title="Who they were to us"
                  subtitle="Hearts whose writing names someone's place in the writer's life."
                  table={mentionTable(insights.relationships, 'Mentioned')}
                >
                  <BarList items={mentions(insights.relationships)} />
                </ChartCard>
              )}

              {insights?.messages?.length > 0 && (
                <ChartCard
                  title="What people wrote"
                  subtitle="Hearts whose writing includes each message. A heart can carry several."
                  table={mentionTable(insights.messages, 'Written')}
                >
                  <BarList items={mentions(insights.messages)} />
                </ChartCard>
              )}

              {candleTributes.length > 0 && (
                <ChartCard
                  wide
                  title="Candles by tribute"
                  subtitle="Candles lit on each tribute."
                  table={{ columns: ['Tribute', 'Candles'], rows: candleTributes.map((t) => [t.name, t.candles]) }}
                >
                  <BarList
                    items={candleTributes.map((t) => ({
                      label: t.name,
                      value: t.candles,
                      tip: stats.candles > 0 ? `${percentText(t.candles, stats.candles)} of all candles lit` : undefined,
                    }))}
                  />
                </ChartCard>
              )}
            </div>
          )}
        </>
      )}
    </section>
  )
}

export default Dashboard
