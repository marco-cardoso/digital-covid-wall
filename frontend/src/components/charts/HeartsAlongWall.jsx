import { useEffect, useMemo, useState } from 'react'
import ChartCard from './ChartCard'
import { binPhotos, columnPath, formatTick, heartsText, niceStep, photosText, visitsOf } from './chartMath'

const HEIGHT = 260
const MARGIN = { top: 32, right: 10, bottom: 30, left: 46 }
const GAP = 2 // px of surface between touching marks
const MIN_SLOT = 6 // px a column and its gap may shrink to, so columns stay thin but visible
const MAX_BAR = 24
const RADIUS = 4
const TABLE_ROW_PHOTOS = 40

/** The element's width in px, kept current as it is resized. */
function useWidth(element, fallback = 760) {
  const [width, setWidth] = useState(fallback)
  useEffect(() => {
    if (!element) return undefined
    const measure = () => {
      const w = Math.round(element.getBoundingClientRect().width)
      if (w > 0) setWidth(w)
    }
    measure()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure)
      return () => window.removeEventListener('resize', measure)
    }
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [element])
  return width
}

const clamp = (value, low, high) => Math.min(high, Math.max(low, value))

/**
 * Hearts counted in each stretch of photos, in order along the wall: thin stacked columns (hearts with
 * writing at the foot, the rest above), the visits to the wall marked along the top. Hover, touch or the
 * arrow keys read out any stretch.
 */
function HeartsAlongWall({ photos }) {
  const [frame, setFrame] = useState(null)
  const width = useWidth(frame)
  const [active, setActive] = useState(null)

  const plotWidth = Math.max(120, width - MARGIN.left - MARGIN.right)
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom
  const perPhoto = plotWidth / Math.max(1, photos.length)
  const size = Math.max(1, Math.ceil(photos.length / Math.max(1, Math.floor(plotWidth / MIN_SLOT))))
  const bins = useMemo(() => (photos.length ? binPhotos(photos, size) : []), [photos, size])
  const visits = useMemo(() => visitsOf(photos), [photos])
  const table = useMemo(
    () => ({
      columns: ['Photos', 'Hearts', 'With writing', 'No writing'],
      rows: binPhotos(photos, TABLE_ROW_PHOTOS).map((bin) => [
        `${bin.first}–${bin.last}`,
        bin.hearts,
        bin.writing,
        bin.blank,
      ]),
    }),
    [photos],
  )

  if (!bins.length) return null

  const busiest = bins.reduce((best, bin) => (bin.hearts > best.hearts ? bin : best), bins[0])
  const maxHearts = busiest.hearts
  const step = niceStep(maxHearts)
  const yMax = Math.max(step, Math.ceil(maxHearts / step) * step)
  const ticks = Array.from({ length: Math.round(yMax / step) + 1 }, (_, i) => i * step)
  const y = (value) => MARGIN.top + plotHeight - (value / yMax) * plotHeight
  const baseline = y(0)
  const xOf = (position) => MARGIN.left + position * perPhoto

  const tickEvery = plotWidth > 600 ? 100 : 200
  const photoTicks = photos
    .map((p, i) => ({ number: p.number, x: xOf(i) }))
    .filter(({ number }) => number === 1 || number % tickEvery === 0)

  const binAt = (clientX, box) => {
    const position = (clientX - box.left - MARGIN.left) / perPhoto
    return clamp(Math.floor(position / size), 0, bins.length - 1)
  }
  const onPointer = (event) => setActive(binAt(event.clientX, event.currentTarget.getBoundingClientRect()))
  const onKeyDown = (event) => {
    const move = { ArrowLeft: -1, ArrowRight: 1 }[event.key]
    if (move !== undefined) {
      setActive((current) => clamp((current ?? busiest.index) + move, 0, bins.length - 1))
    } else if (event.key === 'Home') {
      setActive(0)
    } else if (event.key === 'End') {
      setActive(bins.length - 1)
    } else {
      return
    }
    event.preventDefault()
  }

  const current = active === null ? null : bins[active]
  const centre = current ? xOf(current.start + current.count / 2) : 0

  return (
    <ChartCard
      wide
      title="Hearts along the wall"
      subtitle="Hearts counted in each stretch of photos, in order along the wall. The ones with writing are the ones names can be read from."
      table={table}
    >
      <ul className="viz-legend">
        <li>
          <i className="viz-swatch viz-swatch-accent" aria-hidden="true" />
          With writing
        </li>
        <li>
          <i className="viz-swatch viz-swatch-context" aria-hidden="true" />
          No writing
        </li>
      </ul>

      <div
        ref={setFrame}
        className="viz-frame"
        tabIndex={0}
        role="group"
        aria-label="Hearts along the wall. Use the left and right arrow keys to read each stretch of photos."
        onKeyDown={onKeyDown}
        onBlur={() => setActive(null)}
      >
        <svg
          className="viz-svg"
          width={width}
          height={HEIGHT}
          role="img"
          aria-label={`Hearts counted along the wall, photo ${photos[0].number} to ${photos[photos.length - 1].number}. The busiest stretch is ${photosText(busiest).toLowerCase()} with ${heartsText(busiest.hearts)}.`}
          onPointerDown={onPointer}
          onPointerMove={onPointer}
          onPointerLeave={() => setActive(null)}
        >
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={MARGIN.left}
                x2={width - MARGIN.right}
                y1={y(tick)}
                y2={y(tick)}
                className={tick === 0 ? 'viz-axis' : 'viz-grid'}
              />
              <text x={MARGIN.left - 8} y={y(tick)} dy="0.32em" textAnchor="end" className="viz-tick">
                {formatTick(tick)}
              </text>
            </g>
          ))}

          {current && (
            <rect
              className="viz-band"
              x={xOf(current.start)}
              y={MARGIN.top}
              width={current.count * perPhoto}
              height={plotHeight}
            />
          )}

          {bins.map((bin) => {
            const slot = bin.count * perPhoto
            const barWidth = clamp(slot - GAP, 1, MAX_BAR)
            const x = xOf(bin.start) + (slot - barWidth) / 2
            const writingTop = y(bin.writing)
            // the writing segment sits on the baseline; a surface gap separates it from the rest above
            const blankHeight = Math.max(0, writingTop - y(bin.hearts) - (bin.writing > 0 ? GAP : 0))
            return (
              <g
                key={bin.index}
                className={active === bin.index ? 'viz-column viz-column-active' : 'viz-column'}
                style={{ '--i': bin.index }}
              >
                {bin.writing > 0 && (
                  <path
                    className="viz-fill-accent"
                    d={
                      bin.blank > 0
                        ? `M${x},${baseline}V${writingTop}H${x + barWidth}V${baseline}Z`
                        : columnPath(x, writingTop, barWidth, baseline - writingTop, RADIUS)
                    }
                  />
                )}
                {bin.blank > 0 && (
                  <path
                    className="viz-fill-context"
                    d={columnPath(x, y(bin.hearts), barWidth, blankHeight, RADIUS)}
                  />
                )}
              </g>
            )
          })}

          {visits.map((visit, i) => {
            const x0 = xOf(visit.start)
            const room = (visit.end - visit.start) * perPhoto
            return (
              <g key={visit.label}>
                {i > 0 && <line x1={x0} x2={x0} y1={MARGIN.top - 18} y2={baseline} className="viz-visit-line" />}
                {room > visit.label.length * 6.4 + 12 && (
                  <text x={x0 + 6} y={MARGIN.top - 8} className="viz-visit">
                    {visit.label}
                  </text>
                )}
              </g>
            )
          })}

          {current && <line className="viz-cross" x1={centre} x2={centre} y1={MARGIN.top} y2={baseline} />}

          {photoTicks.map(({ number, x }) => (
            <text
              key={number}
              x={x}
              y={HEIGHT - 8}
              textAnchor={number === 1 ? 'start' : 'middle'}
              className="viz-tick"
            >
              {number}
            </text>
          ))}
        </svg>

        {current && (
          <div
            className="viz-tip viz-tip-float"
            style={{
              left: centre,
              top: MARGIN.top,
              transform: centre > width * 0.6 ? 'translateX(calc(-100% - 12px))' : 'translateX(12px)',
            }}
          >
            <span className="viz-tip-title">{photosText(current)}</span>
            <span className="viz-tip-value">{heartsText(current.hearts)}</span>
            <span className="viz-tip-row">
              <i className="viz-key viz-key-accent" aria-hidden="true" />
              With writing <b>{current.writing.toLocaleString()}</b>
            </span>
            <span className="viz-tip-row">
              <i className="viz-key viz-key-context" aria-hidden="true" />
              No writing <b>{current.blank.toLocaleString()}</b>
            </span>
          </div>
        )}
      </div>

      <p className="viz-axis-title">Photo number, left to right along the wall</p>
      <p className="viz-note">
        Busiest stretch: {photosText(busiest).toLowerCase()}, {heartsText(busiest.hearts)}.
        {visits.length > 0 && ` Photographed ${visits.map((visit) => visit.label).join(' and ')}.`}
      </p>
      <p className="viz-sr" aria-live="polite">
        {current
          ? `${photosText(current)}: ${heartsText(current.hearts)}, ${current.writing.toLocaleString()} with writing.`
          : ''}
      </p>
    </ChartCard>
  )
}

export default HeartsAlongWall
