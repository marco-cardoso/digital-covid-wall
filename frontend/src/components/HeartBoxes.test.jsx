import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchHeartBoxes } from '../api'
import HeartBoxes from './HeartBoxes'

vi.mock('openseadragon', () => ({
  default: {
    Point: class {
      constructor(x, y) {
        Object.assign(this, { x, y })
      }
    },
  },
}))
vi.mock('../api')

const INFO = { width: 30000, height: 3000 }
const INDEX = {
  dzi: '/wall/wall.dzi',
  photos: [
    { number: 1, file: '0001.json', x0: 0, x1: 2000 },
    { number: 2, file: '0002.json', x0: 2000, x1: 4000 },
    { number: 9, file: '0009.json', x0: 24000, x1: 26000 },
  ],
}
// rows are [x, y, w, h, writing, n] in wall pixels; the stand-in viewer below shows each as a tenth of that on screen
const CHUNKS = {
  '0001.json': {
    hearts: [
      [100, 400, 300, 300, 0, 1], // a big one (30 px on screen, at 10..40 x 40..70) ...
      [150, 450, 100, 100, 1, 2], // ... with a smaller heart inside it (15..25 x 45..55)
      [1500, 500, 5, 5, 0, 3], // far too small to see (half a pixel)
      [100, 20, 200, 100, 0, 4], // near the top of the screen (10..30 x 2..12)
    ],
  },
  '0002.json': { hearts: [[2500, 800, 200, 200, 1, 1]] },
  '0009.json': { hearts: [[24500, 800, 200, 200, 1, 1]] },
}

// A stand-in for the OpenSeadragon viewer: a 1000 x 500 screen on which one wall pixel is `k` screen pixels.
function makeViewer() {
  const handlers = {}
  const element = document.createElement('div')
  element.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 500 })
  const view = { ox: 0, oy: 0, k: 0.1 }
  const at = (point) => ({ x: view.ox + point.x * INFO.width * view.k, y: view.oy + point.y * INFO.width * view.k })
  const viewer = {
    element,
    viewport: { getContainerSize: () => ({ x: 1000, y: 500 }), pixelFromPoint: vi.fn(at) },
    addHandler: vi.fn((name, fn) => {
      handlers[name] = [...(handlers[name] ?? []), fn]
    }),
    removeHandler: vi.fn((name, fn) => {
      handlers[name] = (handlers[name] ?? []).filter((h) => h !== fn)
    }),
  }
  const fire = (name, event) => act(() => handlers[name]?.forEach((fn) => fn(event)))
  return { viewer, view, handlers, fire }
}

// A canvas that records what is stroked, in place of the one jsdom lacks. Each clear starts a new picture.
function fakeCanvas() {
  const strokes = []
  const ctx = {
    setTransform: vi.fn(),
    clearRect: vi.fn(() => {
      strokes.length = 0
    }),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    arcTo: vi.fn(),
    closePath: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(() => strokes.push({ style: ctx.strokeStyle, width: ctx.lineWidth, alpha: ctx.globalAlpha, fill: ctx.fillStyle })),
  }
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(ctx)
  return { ctx, strokes }
}

const pointer = (target, type, x, y, pointerType = 'mouse') =>
  act(() => {
    const event = new MouseEvent(type, { clientX: x, clientY: y, bubbles: true })
    Object.defineProperty(event, 'pointerType', { value: pointerType })
    target.dispatchEvent(event)
  })

const setup = async (props = {}) => {
  const stage = makeViewer()
  const canvas = fakeCanvas()
  const onCount = vi.fn()
  const onOpen = vi.fn()
  const rendered = render(<HeartBoxes viewer={stage.viewer} info={INFO} index={INDEX} active onCount={onCount} onOpen={onOpen} {...props} />)
  await waitFor(() => expect(fetchHeartBoxes).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(canvas.strokes.length).toBeGreaterThan(0))
  return { ...stage, ...canvas, onCount, onOpen, rendered }
}

describe('HeartBoxes', () => {
  beforeEach(() => {
    fetchHeartBoxes.mockImplementation(async (file) => CHUNKS[file])
    window.matchMedia = vi.fn(() => ({ matches: true })) // reduced motion: boxes appear at once
    Object.defineProperty(window, 'devicePixelRatio', { value: 1, configurable: true })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    delete window.matchMedia
  })

  it('fetches the photos near the view and draws a box for every heart that can be seen', async () => {
    const { strokes } = await setup()

    // photo 1: three visible hearts (the 0.5 px one is skipped); photo 2: one
    expect(strokes).toHaveLength(4)
    expect(fetchHeartBoxes).toHaveBeenCalledWith('0001.json')
    expect(fetchHeartBoxes).toHaveBeenCalledWith('0002.json')
    expect(fetchHeartBoxes).not.toHaveBeenCalledWith('0009.json') // too far along the wall to want yet
  })

  it('draws hearts with writing in gold and the others in white', async () => {
    const { strokes } = await setup()

    const gold = strokes.filter((s) => s.style.startsWith('rgba(246, 196, 83'))
    const white = strokes.filter((s) => s.style.startsWith('rgba(255, 255, 255'))
    expect(gold).toHaveLength(2) // hearts 2 (photo 1) and 1 (photo 2)
    expect(white).toHaveLength(2)
    expect(gold[0].fill).toMatch(/0\.13\)$/) // a faint wash on the ones with writing
    expect(white[0].fill).toMatch(/, 0\)$/)
    expect(strokes.every((s) => s.alpha === 1)).toBe(true)
  })

  it('tells the page how many hearts are in view, and that photos were still loading at first', async () => {
    const { onCount } = await setup()

    expect(onCount.mock.calls[0][0]).toEqual({ hearts: 0, writing: 0, pending: true })
    expect(onCount).toHaveBeenLastCalledWith({ hearts: 4, writing: 2, pending: false })
  })

  it('counts only the hearts that are on screen', async () => {
    const { view, fire, onCount } = await setup()

    view.ox = -2300 * view.k // slide the view along so that only photo 2 is on screen
    await fire('viewport-change')
    expect(onCount).toHaveBeenLastCalledWith({ hearts: 1, writing: 1, pending: false })
  })

  it('looks for more boxes as the view moves along, once for each photo', async () => {
    const { view, fire } = await setup()

    view.ox = -22000 * view.k // photo 9 is now within a view-width
    await fire('viewport-change')
    await waitFor(() => expect(fetchHeartBoxes).toHaveBeenCalledWith('0009.json'))
    await fire('viewport-change')
    await fire('resize')
    expect(fetchHeartBoxes.mock.calls.filter(([file]) => file === '0009.json')).toHaveLength(1)
  })

  it('carries on without the boxes of a photo that could not be fetched', async () => {
    fetchHeartBoxes.mockImplementation(async (file) => {
      if (file === '0002.json') throw new Error('gone')
      return CHUNKS[file]
    })
    const { strokes, onCount } = await setup()

    expect(strokes).toHaveLength(3)
    expect(onCount).toHaveBeenLastCalledWith({ hearts: 3, writing: 1, pending: true }) // it never arrives
  })

  it('draws nothing while the viewer has no size yet', async () => {
    const stage = makeViewer()
    stage.view.k = 0
    const { strokes } = fakeCanvas()
    render(<HeartBoxes viewer={stage.viewer} info={INFO} index={INDEX} active onCount={vi.fn()} />)

    expect(strokes).toHaveLength(0)
    expect(fetchHeartBoxes).not.toHaveBeenCalled()
  })

  it('sizes the canvas to the viewer, sharply on a dense screen', async () => {
    Object.defineProperty(window, 'devicePixelRatio', { value: 2, configurable: true })
    const { rendered, ctx } = await setup()

    const canvas = rendered.container.querySelector('canvas')
    expect([canvas.width, canvas.height]).toEqual([2000, 1000])
    expect([canvas.style.width, canvas.style.height]).toEqual(['1000px', '500px'])
    expect(ctx.setTransform).toHaveBeenLastCalledWith(2, 0, 0, 2, 0, 0)
  })

  it('brings the boxes in as a wave from the left, then stops asking for frames', async () => {
    delete window.matchMedia // motion is fine
    const frames = []
    vi.stubGlobal('requestAnimationFrame', (fn) => frames.push(fn))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    const clock = vi.spyOn(performance, 'now').mockReturnValue(1000)
    const { strokes } = await setup()

    expect(strokes.every((s) => s.alpha === 0)).toBe(true) // nothing shown at the very start
    expect(frames.length).toBeGreaterThan(0)

    clock.mockReturnValue(1250) // half way: the left is ahead of the right
    await act(async () => frames.splice(0).forEach((fn) => fn()))
    const alphas = strokes.map((s) => s.alpha)
    expect(Math.max(...alphas)).toBeGreaterThan(Math.min(...alphas))
    expect(alphas.every((a) => a > 0 && a < 1)).toBe(true)

    clock.mockReturnValue(5000)
    await act(async () => frames.splice(0).forEach((fn) => fn()))
    expect(strokes.every((s) => s.alpha === 1)).toBe(true)
    expect(frames).toHaveLength(0)
    vi.unstubAllGlobals()
  })

  describe('naming a heart', () => {
    const tip = () => screen.queryByTestId('heart-tip')

    it('shows which heart the mouse is over, and lights its box', async () => {
      const { viewer, strokes } = await setup()

      await pointer(viewer.element, 'pointermove', 20, 50) // inside the big heart and the small one: the small one
      expect(tip()).toHaveTextContent('Heart 2')
      expect(tip()).toHaveTextContent('Photo 1 · writing found')
      expect(tip()).toHaveTextContent('Click to open')
      expect(strokes.some((s) => s.width === 2.5)).toBe(true)

      await pointer(viewer.element, 'pointermove', 35, 65) // the big heart's own corner
      expect(tip()).toHaveTextContent('Heart 1')
      expect(tip()).toHaveTextContent('no writing found')

      await pointer(viewer.element, 'pointermove', 800, 400) // nothing there
      expect(tip()).toBeNull()
    })

    it('turns the pointer into a button over a heart, and back again', async () => {
      const { viewer } = await setup()

      await pointer(viewer.element, 'pointermove', 20, 50)
      expect(viewer.element).toHaveClass('is-over-heart')
      await pointer(viewer.element, 'pointermove', 800, 400)
      expect(viewer.element).not.toHaveClass('is-over-heart')
    })

    it('puts the readout below a heart that is near the top of the screen, and above the rest', async () => {
      const { viewer, view, fire } = await setup()

      await pointer(viewer.element, 'pointermove', 20, 5) // heart 4 begins 2 px from the top
      expect(tip()).toHaveTextContent('Heart 4')
      expect(tip()).toHaveClass('heart-tip-below')

      view.oy = 60 // with room above it, the readout goes above
      await fire('viewport-change')
      await pointer(viewer.element, 'pointermove', 20, 110)
      expect(tip()).toHaveTextContent('Heart 2')
      expect(tip()).not.toHaveClass('heart-tip-below')
    })

    it('lets go when the mouse leaves, and ignores touches (a tap opens the heart instead)', async () => {
      const { viewer } = await setup()

      await pointer(viewer.element, 'pointermove', 20, 50, 'touch')
      expect(tip()).toBeNull()
      await pointer(viewer.element, 'pointermove', 20, 50)
      expect(tip()).not.toBeNull()
      await pointer(viewer.element, 'pointerleave', 20, 50)
      expect(tip()).toBeNull()
      expect(viewer.element).not.toHaveClass('is-over-heart')
      await pointer(viewer.element, 'pointerleave', 20, 50) // already nothing: no harm
      expect(tip()).toBeNull()
    })

    it('lets go when the view moves, since the heart is no longer where it was', async () => {
      const { viewer, fire, view } = await setup()

      await pointer(viewer.element, 'pointermove', 20, 50)
      expect(tip()).not.toBeNull()
      view.ox = -50
      await fire('viewport-change')
      expect(tip()).toBeNull()
    })
  })

  describe('opening a heart', () => {
    it('hands the heart that was clicked or tapped to onOpen, with its place on the wall', async () => {
      const { fire, onOpen } = await setup()

      await fire('canvas-click', { quick: true, position: { x: 20, y: 50 } }) // the small heart inside the big one
      expect(onOpen).toHaveBeenCalledTimes(1)
      expect(onOpen).toHaveBeenCalledWith({ photo: 1, number: 2, writing: true, box: { x: 150, y: 450, w: 100, h: 100 } })

      await fire('canvas-click', { quick: true, position: { x: 270, y: 90 } }) // a heart of photo 2
      expect(onOpen).toHaveBeenLastCalledWith({ photo: 2, number: 1, writing: true, box: { x: 2500, y: 800, w: 200, h: 200 } })
    })

    it('reports a heart without writing as such', async () => {
      const { fire, onOpen } = await setup()

      await fire('canvas-click', { quick: true, position: { x: 35, y: 65 } })
      expect(onOpen).toHaveBeenCalledWith({ photo: 1, number: 1, writing: false, box: { x: 100, y: 400, w: 300, h: 300 } })
    })

    it('puts the readout away, since the heart is open now', async () => {
      const { viewer, fire } = await setup()

      await pointer(viewer.element, 'pointermove', 20, 50)
      expect(screen.queryByTestId('heart-tip')).not.toBeNull()
      await fire('canvas-click', { quick: true, position: { x: 20, y: 50 } })
      expect(screen.queryByTestId('heart-tip')).toBeNull()
      expect(viewer.element).not.toHaveClass('is-over-heart')
    })

    it('does nothing for a click on bare wall, or for a drag that ended where it began', async () => {
      const { fire, onOpen } = await setup()

      await fire('canvas-click', { quick: true, position: { x: 900, y: 450 } })
      await fire('canvas-click', { quick: false, position: { x: 20, y: 50 } })
      expect(onOpen).not.toHaveBeenCalled()
    })

    it('is fine with nobody listening', async () => {
      const { fire } = await setup({ onOpen: undefined })

      await fire('canvas-click', { quick: true, position: { x: 20, y: 50 } })
    })
  })

  describe('when switched off', () => {
    it('keeps its canvas hidden, listens to nothing and fetches nothing', () => {
      const stage = makeViewer()
      fakeCanvas()
      const { container } = render(<HeartBoxes viewer={stage.viewer} info={INFO} index={INDEX} active={false} onCount={vi.fn()} />)

      expect(container.querySelector('canvas')).toHaveAttribute('hidden')
      expect(stage.viewer.addHandler).not.toHaveBeenCalled()
      expect(fetchHeartBoxes).not.toHaveBeenCalled()
    })

    it('clears the picture, forgets the count and removes its listeners when switched off', async () => {
      const { rendered, viewer, ctx, onCount, handlers } = await setup()

      rendered.rerender(<HeartBoxes viewer={viewer} info={INFO} index={INDEX} active={false} onCount={onCount} />)

      expect(ctx.clearRect).toHaveBeenCalled()
      expect(onCount).toHaveBeenLastCalledWith(null)
      expect(Object.values(handlers).flat()).toHaveLength(0)
      expect(viewer.removeHandler).toHaveBeenCalledTimes(3)
    })

    it('keeps the boxes it has fetched for next time', async () => {
      const { rendered, viewer, onCount, strokes } = await setup()

      rendered.rerender(<HeartBoxes viewer={viewer} info={INFO} index={INDEX} active={false} onCount={onCount} />)
      rendered.rerender(<HeartBoxes viewer={viewer} info={INFO} index={INDEX} active onCount={onCount} />)

      expect(fetchHeartBoxes).toHaveBeenCalledTimes(2)
      expect(strokes).toHaveLength(4)
    })
  })

  it('draws nothing when there is no canvas to draw on, or no viewer yet', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    const stage = makeViewer()
    const { rerender } = render(<HeartBoxes viewer={stage.viewer} info={INFO} index={INDEX} active onCount={vi.fn()} />)
    expect(stage.viewer.addHandler).not.toHaveBeenCalled()

    rerender(<HeartBoxes viewer={null} info={INFO} index={INDEX} active onCount={vi.fn()} />)
    expect(fetchHeartBoxes).not.toHaveBeenCalled()
  })

  it('works without anyone listening to the count', async () => {
    const stage = makeViewer()
    const { strokes } = fakeCanvas()
    const { unmount } = render(<HeartBoxes viewer={stage.viewer} info={INFO} index={INDEX} active />)

    await waitFor(() => expect(strokes.length).toBeGreaterThan(0))
    unmount()
  })
})
