import { useCallback, useEffect, useRef, useState } from 'react'
import OpenSeadragon from 'openseadragon'
import { fetchWallInfo } from '../api'

const ZOOM_STEP = 1.5
// The wall fills this share of the viewer's height, leaving equal bars above and below.
const FILL = 0.82
// How far past the fitted view visitors may zoom out / in.
const MIN_ZOOM_FACTOR = 0.25
const MAX_ZOOM_PIXEL_RATIO = 2
const SLIDER_STEPS = 1000

const clamp01 = (v) => Math.min(1, Math.max(0, v))

function WallPanorama() {
  const [info, setInfo] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [position, setPosition] = useState(0)
  const [view, setView] = useState({ left: 0, width: 0 })
  const [segment, setSegment] = useState('')
  const [photo, setPhoto] = useState(null)
  const containerRef = useRef(null)
  const viewerRef = useRef(null)
  const fitHeightRef = useRef(null)

  useEffect(() => {
    const load = async () => {
      try {
        setInfo(await fetchWallInfo())
      } catch (err) {
        setError(
          err.status === 404
            ? 'The stitched wall has not been built yet.'
            : err.message || 'Could not load the wall.',
        )
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  useEffect(() => {
    if (!info) return undefined
    const aspect = info.height / info.width
    const viewer = OpenSeadragon({
      element: containerRef.current,
      tileSources: info.dzi,
      showNavigationControl: false,
      visibilityRatio: 1,
      constrainDuringPan: true,
      maxZoomPixelRatio: MAX_ZOOM_PIXEL_RATIO,
      // The wheel scrolls the page past the wall; Ctrl/Cmd + wheel (or two fingers) zooms it.
      cooperativeGestures: true,
      gestureSettingsMouse: { clickToZoom: false },
    })
    viewerRef.current = viewer
    const { viewport } = viewer

    // Fit the wall to FILL of the viewer's height, centred, at a given spot along it.
    fitHeightRef.current = (centreX) => {
      const { x: w, y: h } = viewport.getContainerSize()
      const viewHeight = aspect / FILL
      const viewWidth = viewHeight * (w / h)
      const x = centreX === undefined ? 0 : centreX - viewWidth / 2
      viewport.fitBounds(new OpenSeadragon.Rect(x, aspect / 2 - viewHeight / 2, viewWidth, viewHeight), true)
      viewport.minZoomLevel = viewport.getZoom() * MIN_ZOOM_FACTOR
    }

    viewer.addHandler('open', () => {
      fitHeightRef.current()
      // Joins sit in the bars, outside the wall: a notch above and below, and a label
      // where a stretch between visits wasn't photographed.
      const mark = (className, x, y, placement, text) => {
        const element = document.createElement('div')
        element.className = className
        if (text) element.textContent = text
        viewer.addOverlay({ element, location: new OpenSeadragon.Point(x, y), placement })
      }
      for (const brk of info.breaks ?? []) {
        const x = brk.x / info.width
        mark('wall-notch wall-notch-top', x, -aspect * 0.015, OpenSeadragon.Placement.BOTTOM)
        mark('wall-notch wall-notch-bottom', x, aspect * 1.015, OpenSeadragon.Placement.TOP)
        if (brk.kind === 'gap') {
          mark('wall-gap-label', x, -aspect * 0.045, OpenSeadragon.Placement.BOTTOM, brk.label ?? 'Not photographed')
        }
      }
    })

    viewer.addHandler('viewport-change', () => {
      const bounds = viewport.getBounds()
      const centre = viewport.getCenter()
      // While the whole height fits, keep the wall centred between the bars.
      const fits = bounds.height >= aspect
      viewer.panVertical = !fits
      if (fits && Math.abs(centre.y - aspect / 2) > aspect * 1e-3) {
        viewport.panTo(new OpenSeadragon.Point(centre.x, aspect / 2), true)
      }
      const x = clamp01(centre.x)
      setPosition(Math.round(x * SLIDER_STEPS))
      const left = clamp01(bounds.x)
      setView({ left, width: clamp01(bounds.x + bounds.width) - left })
      const px = x * info.width
      const current = (info.segments ?? []).find((seg) => px >= seg.x && px < seg.x + seg.width)
      setSegment(current?.label ?? '')
      // photos are listed left to right by where each starts
      setPhoto((info.photos ?? []).findLast((p) => p.x <= px) ?? null)
    })

    return () => {
      viewer.destroy()
      viewerRef.current = null
    }
  }, [info])

  const zoomBy = useCallback((factor) => {
    const { viewport } = viewerRef.current
    viewport.zoomBy(factor)
    viewport.applyConstraints()
  }, [])

  const resetZoom = () => {
    fitHeightRef.current(viewerRef.current.viewport.getCenter().x)
  }

  const walk = (direction) => {
    const { viewport } = viewerRef.current
    const bounds = viewport.getBounds()
    viewport.panBy(new OpenSeadragon.Point(direction * bounds.width * 0.8, 0))
    viewport.applyConstraints()
  }

  const jumpTo = (event) => {
    const { viewport } = viewerRef.current
    const centre = viewport.getCenter()
    const x = Number(event.target.value) / SLIDER_STEPS
    viewport.panTo(new OpenSeadragon.Point(x, centre.y), true)
    viewport.applyConstraints(true)
  }

  return (
    <section className="wall" aria-label="Photos of the memorial wall">
      <header className="section-intro">
        <p className="overline">Albert Embankment, London</p>
        <h2>Walk the wall</h2>
        <p className="lede">
          The National Covid Memorial Wall, stitched together from hundreds of
          photos. Walk along it, then zoom in (+, or Ctrl/⌘ and scroll) to read
          the messages written on the hearts.
        </p>
      </header>

      {loading && <p className="status">Loading the wall…</p>}
      {error && <p className="status status-error">{error}</p>}

      {info && (
        <>
          <div className="stage">
            <div className="stage-bar stage-bar-top">
              <div className="stage-caption">
                <p className="stage-place" aria-live="polite">
                  {segment}
                </p>
                {photo && (
                  <p className="stage-photo" title="The photo at the centre of the view">
                    Photo {photo.number} of {info.photoTotal}
                    <span className="stage-photo-file">{photo.file}</span>
                  </p>
                )}
              </div>
              <div className="stage-tools" role="group" aria-label="Zoom the wall">
                <button type="button" className="stage-button" aria-label="Zoom out" onClick={() => zoomBy(1 / ZOOM_STEP)}>
                  −
                </button>
                <button type="button" className="stage-button" aria-label="Zoom in" onClick={() => zoomBy(ZOOM_STEP)}>
                  +
                </button>
                <button type="button" className="stage-button stage-button-text" onClick={resetZoom}>
                  Fit height
                </button>
              </div>
            </div>

            <div className="stage-canvas">
              <div ref={containerRef} className="wall-viewer" data-testid="wall-viewer" />
              <button
                type="button"
                className="stage-arrow stage-arrow-left"
                aria-label="Walk left along the wall"
                onClick={() => walk(-1)}
              >
                ‹
              </button>
              <button
                type="button"
                className="stage-arrow stage-arrow-right"
                aria-label="Walk right along the wall"
                onClick={() => walk(1)}
              >
                ›
              </button>
            </div>

            <div className="stage-bar stage-bar-bottom">
              <div
                className="wall-map"
                style={info.overview ? { backgroundImage: `url("${info.overview}")` } : undefined}
              >
                <div
                  className="wall-map-window"
                  data-testid="wall-map-window"
                  style={{ left: `${view.left * 100}%`, width: `${view.width * 100}%` }}
                />
                <input
                  type="range"
                  className="wall-map-slider"
                  aria-label="Position along the wall"
                  min="0"
                  max={SLIDER_STEPS}
                  value={position}
                  onChange={jumpTo}
                />
              </div>
            </div>
          </div>

          <ul className="stage-legend">
            <li>
              <span className="legend-notch" aria-hidden="true" />
              Neighbouring photos joined without an overlap
            </li>
            <li>
              <span className="legend-notch" aria-hidden="true" />
              <span className="legend-label" aria-hidden="true">Not photographed</span>
              A stretch between visits nobody photographed
            </li>
          </ul>
        </>
      )}
    </section>
  )
}

export default WallPanorama
