import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchWallPhotos } from '../api'

const ZOOM_MIN = 1
const ZOOM_MAX = 4
const ZOOM_STEP = 0.5

function WallPanorama() {
  const [photos, setPhotos] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [zoom, setZoom] = useState(1)
  const stripRef = useRef(null)
  const dragRef = useRef(null)
  const zoomRef = useRef(1)

  useEffect(() => {
    const load = async () => {
      try {
        setPhotos(await fetchWallPhotos())
      } catch (err) {
        setError(err.message || 'Could not load the wall photos.')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  // Zoom by scaling the strip's --slice-h, keeping the point under the anchor
  // (cursor, or the viewport centre for the buttons) fixed as the strip widens.
  const applyZoom = useCallback((next, anchorX) => {
    const clamped = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next))
    const strip = stripRef.current
    const previous = zoomRef.current
    if (strip && clamped !== previous) {
      const rect = strip.getBoundingClientRect()
      const ax = anchorX == null ? rect.width / 2 : anchorX - rect.left
      const ratio = clamped / previous
      strip.scrollLeft = (strip.scrollLeft + ax) * ratio - ax
    }
    zoomRef.current = clamped
    setZoom(clamped)
  }, [])

  // Ctrl/Cmd + wheel zooms. Registered natively so preventDefault isn't passive.
  useEffect(() => {
    const strip = stripRef.current
    if (!strip) return undefined
    const onWheel = (event) => {
      if (!event.ctrlKey && !event.metaKey) return
      event.preventDefault()
      const factor = event.deltaY < 0 ? 1 + ZOOM_STEP : 1 / (1 + ZOOM_STEP)
      applyZoom(zoomRef.current * factor, event.clientX)
    }
    strip.addEventListener('wheel', onWheel, { passive: false })
    return () => strip.removeEventListener('wheel', onWheel)
  }, [applyZoom, photos.length])

  const scrollByViewport = (direction) => {
    const strip = stripRef.current
    strip.scrollBy({ left: direction * strip.clientWidth * 0.8, behavior: 'smooth' })
  }

  const startDrag = (event) => {
    dragRef.current = {
      startX: event.clientX,
      startScroll: stripRef.current.scrollLeft,
    }
  }

  const moveDrag = (event) => {
    const drag = dragRef.current
    if (!drag) return
    stripRef.current.scrollLeft = drag.startScroll - (event.clientX - drag.startX)
  }

  const endDrag = () => {
    dragRef.current = null
  }

  return (
    <section className="panorama" aria-label="Photos of the memorial wall">
      <h2>Walk the wall</h2>
      <p className="panorama-hint">
        Photos of the National Covid Memorial Wall in London. Drag the wall or
        use the arrows to move along it; zoom in for a closer look.
      </p>

      {photos.length > 0 && (
        <div className="panorama-zoom" role="group" aria-label="Zoom the wall">
          <button
            type="button"
            className="panorama-arrow"
            aria-label="Zoom out"
            onClick={() => applyZoom(zoomRef.current - ZOOM_STEP)}
            disabled={zoom <= ZOOM_MIN}
          >
            −
          </button>
          <span className="panorama-zoom-level" aria-live="polite">
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            className="panorama-arrow"
            aria-label="Zoom in"
            onClick={() => applyZoom(zoomRef.current + ZOOM_STEP)}
            disabled={zoom >= ZOOM_MAX}
          >
            +
          </button>
          <button
            type="button"
            className="panorama-reset"
            onClick={() => applyZoom(1)}
            disabled={zoom === 1}
          >
            Reset
          </button>
        </div>
      )}

      {loading && <p className="status">Loading the wall…</p>}
      {error && <p className="status status-error">{error}</p>}
      {!loading && !error && photos.length === 0 && (
        <p className="status">
          No photos yet. Add JPGs to <code>frontend/public/pictures</code> and
          run <code>scripts/build_wall.py</code> — they are displayed side by
          side in filename order, with overlapping areas cropped away.
        </p>
      )}

      {photos.length > 0 && (
        <div className="panorama-viewport">
          <button
            type="button"
            className="panorama-arrow"
            aria-label="Scroll the wall left"
            onClick={() => scrollByViewport(-1)}
          >
            ‹
          </button>
          <div
            ref={stripRef}
            className="wall-strip"
            style={{ '--zoom': zoom }}
            onPointerDown={startDrag}
            onPointerMove={moveDrag}
            onPointerUp={endDrag}
            onPointerLeave={endDrag}
          >
            {photos.map((photo, index) => {
              const { width, height } = photo
              // Source rectangle shown for this photo, in web-copy pixels.
              // Falls back to the legacy cropRight-only geometry.
              const srcX = photo.srcX ?? 0
              const srcY = photo.srcY ?? 0
              const srcW = photo.srcW ?? width - (photo.cropRight ?? 0)
              const srcH = photo.srcH ?? height
              return (
                <div
                  key={photo.file}
                  className="wall-slice"
                  style={{ width: `calc(var(--slice-h) * ${srcW / srcH})` }}
                >
                  <img
                    src={`/pictures/web/${photo.file}`}
                    alt={`Section ${index + 1} of the memorial wall`}
                    loading="lazy"
                    draggable={false}
                    style={{
                      width: `calc(var(--slice-h) * ${width / srcH})`,
                      height: `calc(var(--slice-h) * ${height / srcH})`,
                      left: `calc(var(--slice-h) * ${-srcX / srcH})`,
                      top: `calc(var(--slice-h) * ${-srcY / srcH})`,
                    }}
                  />
                </div>
              )
            })}
          </div>
          <button
            type="button"
            className="panorama-arrow"
            aria-label="Scroll the wall right"
            onClick={() => scrollByViewport(1)}
          >
            ›
          </button>
        </div>
      )}
    </section>
  )
}

export default WallPanorama
