import { useCallback, useEffect, useId, useRef, useState } from 'react'
import OpenSeadragon from 'openseadragon'

const PADDING = 0.4 // how much wall to leave around the heart, as a share of its longer side
const ZOOM_STEP = 1.6
const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

/**
 * A heart, opened: the wall's own pixels around it in a viewer of its own, ready to zoom into and look
 * around, with a way to bring the writing out. `heart` is { photo, number, writing, box }, the box being
 * the heart's place on the wall in full-size wall pixels. It closes on Esc, on a click outside the card
 * and on its close button, and gives focus back to whatever had it.
 */
function HeartDialog({ heart, info, onClose }) {
  const titleId = useId()
  const cardRef = useRef(null)
  const closeRef = useRef(null)
  const viewerElementRef = useRef(null)
  const viewerRef = useRef(null)
  const [clear, setClear] = useState(false)

  useEffect(() => {
    const before = document.activeElement
    closeRef.current.focus()
    return () => before?.focus?.()
  }, [])

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  // the heart and some wall around it, in the viewer's units (the wall is 1 wide)
  const { x, y, w, h } = heart.box
  const wallWidth = info.width
  const frame = useCallback(() => {
    const pad = Math.max(w, h) * PADDING
    return new OpenSeadragon.Rect((x - pad) / wallWidth, (y - pad) / wallWidth, (w + 2 * pad) / wallWidth, (h + 2 * pad) / wallWidth)
  }, [x, y, w, h, wallWidth])

  useEffect(() => {
    const viewer = OpenSeadragon({
      element: viewerElementRef.current,
      tileSources: info.dzi,
      showNavigationControl: false,
      maxZoomPixelRatio: 6,
      visibilityRatio: 0.2,
      animationTime: 0.8,
      gestureSettingsMouse: { clickToZoom: false },
    })
    viewerRef.current = viewer
    viewer.addHandler('open', () => viewer.viewport.fitBounds(frame(), true))
    return () => {
      viewer.destroy()
      viewerRef.current = null
    }
  }, [info.dzi, frame])

  const zoom = (factor) => {
    viewerRef.current.viewport.zoomBy(factor)
    viewerRef.current.viewport.applyConstraints()
  }

  // Tab goes round the card instead of out into the wall behind it.
  const keepFocusInside = (event) => {
    if (event.key !== 'Tab') return
    const items = [...cardRef.current.querySelectorAll(FOCUSABLE)].filter((item) => !item.disabled)
    const first = items[0]
    const last = items[items.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return (
    <div
      className="heart-sheet"
      data-testid="heart-sheet"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section ref={cardRef} className="heart-card" role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={keepFocusInside}>
        <header className="heart-card-head">
          <div>
            <h3 id={titleId}>Heart {heart.number}</h3>
            <p>
              Photo {heart.photo} of {info.photoTotal} · {heart.writing ? 'writing found' : 'no writing found'}
            </p>
          </div>
          <button ref={closeRef} type="button" className="heart-card-close" aria-label="Close" onClick={onClose}>
            <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
              <path d="M3 3l10 10M13 3L3 13" />
            </svg>
          </button>
        </header>

        <div ref={viewerElementRef} className={`heart-card-viewer${clear ? ' is-clear' : ''}`} data-testid="heart-viewer" />

        <footer className="heart-card-tools">
          <div className="heart-card-zoom" role="group" aria-label="Zoom">
            <button type="button" className="stage-button" aria-label="Zoom out" onClick={() => zoom(1 / ZOOM_STEP)}>
              −
            </button>
            <button type="button" className="stage-button" aria-label="Zoom in" onClick={() => zoom(ZOOM_STEP)}>
              +
            </button>
            <button type="button" className="stage-button stage-button-text" onClick={() => viewerRef.current.viewport.fitBounds(frame())}>
              Back to the heart
            </button>
          </div>
          <button
            type="button"
            className="stage-button stage-button-text heart-card-clear"
            aria-pressed={clear}
            title="Shows the pen darker against the paint, to make the writing easier to read"
            onClick={() => setClear((on) => !on)}
          >
            Clearer writing
          </button>
          <p className="heart-card-hint">Scroll or pinch to zoom · drag to look around</p>
        </footer>

        {/* The writing is dark on red paint: the red channel, stretched, is the pen alone on white. */}
        <svg className="heart-ink-filter" width="0" height="0" aria-hidden="true" focusable="false">
          <filter id="heart-ink" colorInterpolationFilters="sRGB">
            <feColorMatrix type="matrix" values="1.7 0 0 0 -0.4  1.7 0 0 0 -0.4  1.7 0 0 0 -0.4  0 0 0 1 0" />
          </filter>
        </svg>
      </section>
    </div>
  )
}

export default HeartDialog
