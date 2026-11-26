import { useCallback, useEffect, useRef, useState } from 'react'
import OpenSeadragon from 'openseadragon'
import { fetchWallInfo } from '../api'

const ZOOM_STEP = 1.5
// The wall fills the stage's height, less a bar above and below that holds the controls
// and the join markers. The bars are a tenth of the height, within these bounds (px).
const PAD_RATIO = 0.1
const MIN_PAD = 68
const MAX_PAD = 88
// How far past the fitted view visitors may zoom out / in.
const MIN_ZOOM_FACTOR = 0.25
const MAX_ZOOM_PIXEL_RATIO = 2
const WHEEL_ZOOM_SENSITIVITY = 0.003
const HINT_SECONDS = 9
// The screen takes a moment to resize after going full screen or leaving it.
const FULLSCREEN_REFIT_MS = 150
const SLIDER_STEPS = 1000

const clamp01 = (v) => Math.min(1, Math.max(0, v))
const padFor = (height) => Math.min(MAX_PAD, Math.max(MIN_PAD, height * PAD_RATIO))
// Wheel deltas arrive in pixels, lines or pages.
const WHEEL_UNIT = [1, 16, 400]
// The wall opens on this photo (by its number); without it in the list the view starts at the left end.
const INITIAL_PHOTO = 484
// The stitched photos do not all reach the top and bottom of the wall: their ragged edges leave gaps in the
// background colour, up to ~305 px deep at the top and ~132 px at the bottom in the current build (of 3,508).
// A strip this many image pixels deep is hidden along the whole wall at each edge, so both edges are straight
// lines; everything else (fitting, the bars, the join marks, the overview) treats those
// lines as the wall's edges. Measured for this build of the tiles.
const TOP_MASK = 320
const BOTTOM_MASK = 144

// The shown part of the wall: its masked strips in image pixels, and where it runs top to bottom in
// viewport units (the wall is 1 wide).
const wallSpan = (info) => {
  const topPixels = Math.min(TOP_MASK, info.height / 4)
  const bottomPixels = Math.min(BOTTOM_MASK, info.height / 4)
  const top = topPixels / info.width
  const bottom = (info.height - bottomPixels) / info.width
  return { topPixels, bottomPixels, top, bottom, height: bottom - top, middle: (top + bottom) / 2 }
}

// Where the view is centred on opening, as a fraction of the wall's width: the middle of the
// initial photo, which runs from where it starts to where the next one starts.
const initialCentre = (info) => {
  const photos = info.photos ?? []
  const i = photos.findIndex((p) => p.number === INITIAL_PHOTO)
  if (i < 0) return undefined
  const end = photos[i + 1]?.x ?? info.width
  return (photos[i].x + end) / 2 / info.width
}

// A pair of chevrons that flow in the direction of travel (the left arrow is this, mirrored by CSS).
function ArrowIcon() {
  return (
    <svg className="side-arrow-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path className="side-arrow-chevron" d="M4.5 6l6 6-6 6" />
      <path className="side-arrow-chevron" d="M12 6l6 6-6 6" />
    </svg>
  )
}

function WallPanorama() {
  const [info, setInfo] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [position, setPosition] = useState(0)
  const [view, setView] = useState({ left: 0, width: 0 })
  const [segment, setSegment] = useState('')
  const [photo, setPhoto] = useState(null)
  const [hint, setHint] = useState(true)
  const [fullscreen, setFullscreen] = useState(false)
  const stageRef = useRef(null)
  const wasFittedRef = useRef(false)
  const canvasRef = useRef(null)
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

  // The how-to-move hint fades on its own, or as soon as the visitor does something.
  useEffect(() => {
    if (!info) return undefined
    const timer = setTimeout(() => setHint(false), HINT_SECONDS * 1000)
    return () => clearTimeout(timer)
  }, [info])

  // The stage goes full screen as one piece, controls and all. If the whole wall was in view
  // it is fitted to the new height once the screen has resized.
  useEffect(() => {
    let timer
    const onChange = () => {
      setFullscreen(document.fullscreenElement === stageRef.current)
      clearTimeout(timer)
      timer = setTimeout(() => {
        const viewer = viewerRef.current
        if (viewer && wasFittedRef.current) fitHeightRef.current(viewer.viewport.getCenter().x)
      }, FULLSCREEN_REFIT_MS)
    }
    document.addEventListener('fullscreenchange', onChange)
    return () => {
      document.removeEventListener('fullscreenchange', onChange)
      clearTimeout(timer)
    }
  }, [])

  useEffect(() => {
    if (!info) return undefined
    const aspect = info.height / info.width
    const span = wallSpan(info)
    const element = containerRef.current
    const viewer = OpenSeadragon({
      element,
      // The clip hides the masked strips; panning and zoom limits keep to what is left.
      tileSources: {
        tileSource: info.dzi,
        clip: new OpenSeadragon.Rect(0, span.topPixels, info.width, info.height - span.topPixels - span.bottomPixels),
      },
      showNavigationControl: false,
      visibilityRatio: 1,
      constrainDuringPan: true,
      maxZoomPixelRatio: MAX_ZOOM_PIXEL_RATIO,
      // The wheel is handled below: it walks along the wall instead of zooming.
      gestureSettingsMouse: { clickToZoom: false, scrollToZoom: false },
    })
    viewerRef.current = viewer
    const { viewport } = viewer

    // Fit the wall to the stage's height, centred, at a given spot along it.
    fitHeightRef.current = (centreX) => {
      const { x: w, y: h } = viewport.getContainerSize()
      const wallPixels = Math.max(h - 2 * padFor(h), h * 0.3)
      const viewHeight = (span.height * h) / wallPixels
      const viewWidth = viewHeight * (w / h)
      const x = centreX === undefined ? 0 : centreX - viewWidth / 2
      viewport.fitBounds(new OpenSeadragon.Rect(x, span.middle - viewHeight / 2, viewWidth, viewHeight), true)
      viewport.minZoomLevel = viewport.getZoom() * MIN_ZOOM_FACTOR
    }

    viewer.addHandler('open', () => {
      fitHeightRef.current(initialCentre(info))
      // Joins sit in the bars, outside the wall: a notch above and below, and a label
      // where a stretch between visits wasn't photographed.
      const mark = (className, x, y, placement, text) => {
        const marker = document.createElement('div')
        marker.className = className
        if (text) marker.textContent = text
        viewer.addOverlay({ element: marker, location: new OpenSeadragon.Point(x, y), placement })
      }
      for (const brk of info.breaks ?? []) {
        const x = brk.x / info.width
        mark('wall-notch wall-notch-top', x, span.top - aspect * 0.015, OpenSeadragon.Placement.BOTTOM)
        mark('wall-notch wall-notch-bottom', x, span.bottom + aspect * 0.01, OpenSeadragon.Placement.TOP)
        if (brk.kind === 'gap') {
          mark('wall-gap-label', x, span.top - aspect * 0.03, OpenSeadragon.Placement.BOTTOM, brk.label ?? 'Not photographed')
        }
      }
    })

    // Walking: the wheel (or a trackpad swipe) moves along the wall; Ctrl/⌘ + wheel, which is
    // also how a trackpad pinch arrives, zooms about the pointer.
    const onWheel = (event) => {
      event.preventDefault()
      setHint(false)
      const unit = WHEEL_UNIT[event.deltaMode] ?? 1
      if (event.ctrlKey || event.metaKey) {
        const box = element.getBoundingClientRect()
        const about = viewport.pointFromPixel(new OpenSeadragon.Point(event.clientX - box.left, event.clientY - box.top))
        viewport.zoomBy(Math.exp(-event.deltaY * unit * WHEEL_ZOOM_SENSITIVITY), about)
      } else {
        const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY
        const { x: w } = viewport.getContainerSize()
        viewport.panBy(new OpenSeadragon.Point((delta * unit * viewport.getBounds().width) / w, 0))
      }
      viewport.applyConstraints()
    }
    element.addEventListener('wheel', onWheel, { passive: false })
    viewer.addHandler('canvas-press', () => setHint(false))

    viewer.addHandler('viewport-change', () => {
      const bounds = viewport.getBounds()
      const centre = viewport.getCenter()
      // Where the wall's top and bottom edges are on screen, for the glow and hairlines.
      const canvas = canvasRef.current
      if (canvas) {
        const top = viewport.pixelFromPoint(new OpenSeadragon.Point(0, span.top), true).y
        const bottom = viewport.pixelFromPoint(new OpenSeadragon.Point(0, span.bottom), true).y
        canvas.style.setProperty('--wall-top', `${top}px`)
        canvas.style.setProperty('--wall-bottom', `${bottom}px`)
      }
      // While the whole height fits, keep the wall centred between the bars.
      const fits = bounds.height >= span.height
      viewer.panVertical = !fits
      if (fits && Math.abs(centre.y - span.middle) > aspect * 1e-3) {
        viewport.panTo(new OpenSeadragon.Point(centre.x, span.middle), true)
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
      element.removeEventListener('wheel', onWheel)
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

  const toggleFullscreen = () => {
    const { viewport } = viewerRef.current
    wasFittedRef.current = viewport.getBounds().height >= wallSpan(info).height
    const request = document.fullscreenElement ? document.exitFullscreen() : stageRef.current.requestFullscreen()
    // refused (say, by a permissions policy): the wall just stays as it is
    request.catch(() => {})
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

  // Whether the view already reaches an end of the wall (a hair of tolerance for rounding).
  const atStart = view.left <= 0.0005
  const atEnd = view.left + view.width >= 0.9995
  const shown = info ? wallSpan(info) : null

  return (
    <section className="wall" aria-label="Photos of the memorial wall">
      <div ref={stageRef} className="stage">
        <div ref={canvasRef} className="stage-canvas">
          {info && <div ref={containerRef} className="wall-viewer" data-testid="wall-viewer" />}
          {info && <div className="stage-fade stage-fade-left" aria-hidden="true" />}
          {info && <div className="stage-fade stage-fade-right" aria-hidden="true" />}

          {/* Big arrows at either edge, centred on the wall: tap to walk a screen's width along it. They rest
              at the ends of the wall, where there is nowhere further to go. */}
          {info && (
            <>
              <button
                type="button"
                className="side-arrow side-arrow-left"
                aria-label="Look further left along the wall"
                disabled={atStart}
                onClick={() => walk(-1)}
              >
                <ArrowIcon />
              </button>
              <button
                type="button"
                className="side-arrow side-arrow-right"
                aria-label="Look further right along the wall"
                disabled={atEnd}
                onClick={() => walk(1)}
              >
                <ArrowIcon />
              </button>
            </>
          )}

          <div className="hud hud-top">
            <div className="hud-title">
              <p className="overline">Albert Embankment, London</p>
              <h2>Walk the wall</h2>
            </div>

            {info && (
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
            )}

            {info && (
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
                {document.fullscreenEnabled && (
                  <button
                    type="button"
                    className="stage-button"
                    aria-label={fullscreen ? 'Exit full screen' : 'Enter full screen'}
                    aria-pressed={fullscreen}
                    onClick={toggleFullscreen}
                  >
                    <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      {fullscreen ? (
                        <path d="M6 1.5v3.5a1 1 0 0 1-1 1H1.5M10 1.5v3.5a1 1 0 0 0 1 1h3.5M6 14.5V11a1 1 0 0 0-1-1H1.5M10 14.5V11a1 1 0 0 1 1-1h3.5" />
                      ) : (
                        <path d="M1.5 5.5v-3a1 1 0 0 1 1-1h3M10.5 1.5h3a1 1 0 0 1 1 1v3M14.5 10.5v3a1 1 0 0 1-1 1h-3M5.5 14.5h-3a1 1 0 0 1-1-1v-3" />
                      )}
                    </svg>
                  </button>
                )}
                <details className="legend">
                  <summary className="stage-button" aria-label="What the markers mean">
                    i
                  </summary>
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
                </details>
              </div>
            )}
          </div>

          {loading && <p className="status stage-status">Loading the wall…</p>}
          {error && <p className="status status-error stage-status">{error}</p>}

          {info && (
            <p className={`stage-hint${hint ? '' : ' stage-hint-hidden'}`} aria-hidden={!hint}>
              Scroll to walk the wall <i>·</i> Ctrl/⌘ + scroll to zoom in on the hearts <i>·</i> drag to look around
            </p>
          )}

          {info && (
            <div className="hud hud-bottom">
              <div className="dock">
                <button
                  type="button"
                  className="dock-arrow"
                  aria-label="Walk left along the wall"
                  onClick={() => walk(-1)}
                >
                  ‹
                </button>
                <div
                  className="wall-map"
                  style={
                    info.overview
                      ? {
                          backgroundImage: `url("${info.overview}")`,
                          // stretched and shifted so the masked strips fall outside the map
                          backgroundSize: `100% ${((100 * info.height) / (info.height - shown.topPixels - shown.bottomPixels)).toFixed(2)}%`,
                          backgroundPosition: `0 ${((100 * shown.topPixels) / (shown.topPixels + shown.bottomPixels || 1)).toFixed(2)}%`,
                        }
                      : undefined
                  }
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
                <button
                  type="button"
                  className="dock-arrow"
                  aria-label="Walk right along the wall"
                  onClick={() => walk(1)}
                >
                  ›
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

export default WallPanorama
