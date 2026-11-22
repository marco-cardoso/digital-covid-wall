import { useEffect, useRef, useState } from 'react'
import OpenSeadragon from 'openseadragon'
import { fetchHeartBoxes } from '../api'
import { nearView, rowAt, visibleRows } from './heartBoxMath'

const FADE_MS = 500
const MIN_SIDE = 2 // px on screen: a box smaller than this is not drawn
const RADIUS = 3
// Gold reads on red paint and on pale stone alike; white says "a heart, but no writing found".
const WRITING = '246, 196, 83'
const PLAIN = '255, 255, 255'

const clamp01 = (v) => Math.min(1, Math.max(0, v))
const prefersReducedMotion = () =>
  typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

function traceBox(ctx, x, y, w, h) {
  const r = Math.min(RADIUS, w / 2, h / 2)
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}

/**
 * Boxes around the hearts the computer found, drawn over the wall. Each photo's boxes are fetched the
 * first time the view comes near them. A mouse pointer over a box says which heart it is; a click or a tap
 * on one opens it (`onOpen` is given the heart). `onCount` hears how many boxes are in view.
 */
function HeartBoxes({ viewer, info, index, active, onCount, onOpen }) {
  const canvasRef = useRef(null)
  const chunksRef = useRef(new Map()) // photo number -> its chunk; null while loading, or if it could not be had
  const [focus, setFocus] = useState(null) // { chunk, row, x, y, below }

  useEffect(() => {
    if (!viewer || !active) return undefined
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    if (!ctx) return undefined

    const { viewport, element } = viewer
    let alive = true
    let animation = 0
    let shown = { hearts: -1, writing: -1, pending: false }
    let current = null // the box under the mouse, drawn brighter
    const started = performance.now()
    const reduced = prefersReducedMotion()

    const geometry = () => {
      const size = viewport.getContainerSize()
      const origin = viewport.pixelFromPoint(new OpenSeadragon.Point(0, 0), true)
      const unit = viewport.pixelFromPoint(new OpenSeadragon.Point(1, 0), true)
      return { w: size.x, h: size.y, ox: origin.x, oy: origin.y, k: (unit.x - origin.x) / info.width }
    }
    const viewOf = (g) => ({ left: -g.ox / g.k, right: (g.w - g.ox) / g.k, top: -g.oy / g.k, bottom: (g.h - g.oy) / g.k })
    const loaded = () => [...chunksRef.current.values()].filter(Boolean)

    const load = async (photo) => {
      chunksRef.current.set(photo.number, null)
      try {
        const data = await fetchHeartBoxes(photo.file)
        chunksRef.current.set(photo.number, { number: photo.number, x0: photo.x0, x1: photo.x1, rows: data.hearts })
        if (alive) draw()
      } catch {
        // left unloaded for this visit: the wall is still there, just without those outlines
      }
    }

    function draw() {
      const g = geometry()
      if (!(g.k > 0)) return
      const view = viewOf(g)
      let pending = false
      for (const photo of nearView(index.photos, view.left, view.right)) {
        if (!chunksRef.current.has(photo.number)) load(photo)
        pending ||= !chunksRef.current.get(photo.number)
      }

      const ratio = window.devicePixelRatio || 1
      if (canvas.width !== Math.round(g.w * ratio) || canvas.height !== Math.round(g.h * ratio)) {
        canvas.width = Math.round(g.w * ratio)
        canvas.height = Math.round(g.h * ratio)
        canvas.style.width = `${g.w}px`
        canvas.style.height = `${g.h}px`
      }
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
      ctx.clearRect(0, 0, g.w, g.h)

      // the boxes come in as a wave from the left, unless the visitor would rather not have motion
      const t = reduced ? 1 : clamp01((performance.now() - started) / FADE_MS)
      let hearts = 0
      let writing = 0
      for (const { row } of visibleRows(loaded(), view)) {
        const [x, y, w, h, hasWriting] = row
        const sx = g.ox + x * g.k
        const sy = g.oy + y * g.k
        const sw = w * g.k
        const sh = h * g.k
        if (Math.max(sw, sh) < MIN_SIDE) continue
        if (sx + sw / 2 >= 0 && sx + sw / 2 <= g.w && sy + sh / 2 >= 0 && sy + sh / 2 <= g.h) {
          hearts += 1
          writing += hasWriting
        }
        const colour = hasWriting ? WRITING : PLAIN
        const lit = current === row
        ctx.globalAlpha = clamp01(t * 1.6 - (clamp01(sx / g.w) * 0.6))
        ctx.lineWidth = lit ? 2.5 : hasWriting ? 1.6 : 1
        ctx.strokeStyle = `rgba(${colour}, ${lit ? 1 : hasWriting ? 0.95 : 0.75})`
        ctx.fillStyle = `rgba(${colour}, ${lit ? 0.3 : hasWriting ? 0.13 : 0})`
        traceBox(ctx, sx, sy, sw, sh)
        ctx.fill()
        ctx.stroke()
      }
      ctx.globalAlpha = 1

      if (hearts !== shown.hearts || writing !== shown.writing || pending !== shown.pending) {
        shown = { hearts, writing, pending }
        onCount?.(shown)
      }
      if (t < 1 && !animation) {
        animation = requestAnimationFrame(() => {
          animation = 0
          if (alive) draw()
        })
      }
    }

    const pick = (px, py) => {
      const g = geometry()
      const hit = rowAt(visibleRows(loaded(), viewOf(g)), (px - g.ox) / g.k, (py - g.oy) / g.k)
      if (!hit) return null
      const [x, y, w, h] = hit.row
      const top = g.oy + y * g.k
      return { ...hit, x: g.ox + (x + w / 2) * g.k, y: top < 90 ? g.oy + (y + h) * g.k : top, below: top < 90 }
    }
    const focusOn = (next) => {
      current = next?.row ?? null
      element.classList.toggle('is-over-heart', Boolean(next)) // so the pointer can say it is a button
      setFocus(next)
      draw()
    }

    const onPointerMove = (event) => {
      if (event.pointerType !== 'mouse') return
      const box = element.getBoundingClientRect()
      const next = pick(event.clientX - box.left, event.clientY - box.top)
      if (next?.row !== current) focusOn(next)
    }
    const onPointerLeave = () => {
      if (current) focusOn(null)
    }
    // a click or a tap on a heart opens it; one anywhere else does nothing
    const onClick = (event) => {
      if (!event.quick) return
      const hit = pick(event.position.x, event.position.y)
      if (!hit) return
      focusOn(null)
      const [x, y, w, h, writing, number] = hit.row
      onOpen?.({ photo: hit.chunk.number, number, writing: Boolean(writing), box: { x, y, w, h } })
    }
    const onViewChange = () => {
      if (current) focusOn(null)
      else draw()
    }

    viewer.addHandler('viewport-change', onViewChange)
    viewer.addHandler('resize', draw)
    viewer.addHandler('canvas-click', onClick)
    element.addEventListener('pointermove', onPointerMove)
    element.addEventListener('pointerleave', onPointerLeave)
    draw()

    return () => {
      alive = false
      cancelAnimationFrame(animation)
      viewer.removeHandler('viewport-change', onViewChange)
      viewer.removeHandler('resize', draw)
      viewer.removeHandler('canvas-click', onClick)
      element.removeEventListener('pointermove', onPointerMove)
      element.removeEventListener('pointerleave', onPointerLeave)
      element.classList.remove('is-over-heart')
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      setFocus(null)
      onCount?.(null)
    }
  }, [viewer, info, index, active, onCount, onOpen])

  return (
    <>
      <canvas ref={canvasRef} className="heart-boxes" aria-hidden="true" hidden={!active} />
      {active && focus && (
        <div
          className={`heart-tip${focus.below ? ' heart-tip-below' : ''}`}
          style={{ left: focus.x, top: focus.y }}
          data-testid="heart-tip"
        >
          <span className="heart-tip-title">Heart {focus.row[5]}</span>
          <span className="heart-tip-meta">
            Photo {focus.chunk.number} · {focus.row[4] ? 'writing found' : 'no writing found'}
          </span>
          <span className="heart-tip-hint">Click to open</span>
        </div>
      )}
    </>
  )
}

export default HeartBoxes
