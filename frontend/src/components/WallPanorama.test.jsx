import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchHeartIndex, fetchWallInfo } from '../api'
import WallPanorama from './WallPanorama'

// OpenSeadragon draws to a canvas, which jsdom lacks; stand in a recording fake.
const osd = vi.hoisted(() => {
  const state = { handlers: {}, viewer: null, options: null }
  const makeViewer = () => {
    const viewport = {
      minZoomLevel: 0,
      getContainerSize: vi.fn(() => ({ x: 800, y: 400 })),
      fitBounds: vi.fn(),
      getZoom: vi.fn(() => 40),
      zoomBy: vi.fn(),
      zoomTo: vi.fn(),
      applyConstraints: vi.fn(),
      getBounds: vi.fn(() => ({ x: 0.2, y: -0.001, width: 0.05, height: 0.0122 })),
      panBy: vi.fn(),
      panTo: vi.fn(),
      getCenter: vi.fn(() => ({ x: 0.25, y: 0.01 })),
      pixelFromPoint: vi.fn((point) => ({ x: point.x, y: 100 + point.y * 10000 })),
      pointFromPixel: vi.fn((point) => ({ x: point.x / 1000, y: point.y / 1000 })),
    }
    return {
      viewport,
      addHandler: vi.fn((name, fn) => {
        state.handlers[name] = fn
      }),
      addOverlay: vi.fn(),
      destroy: vi.fn(),
    }
  }
  const OpenSeadragon = vi.fn((options) => {
    state.options = options
    state.viewer = makeViewer()
    return state.viewer
  })
  OpenSeadragon.Rect = class {
    constructor(x, y, width, height) {
      Object.assign(this, { x, y, width, height })
    }
  }
  OpenSeadragon.Point = class {
    constructor(x, y) {
      Object.assign(this, { x, y })
    }
  }
  OpenSeadragon.Placement = { CENTER: 'center', TOP: 'top', BOTTOM: 'bottom' }
  return { state, OpenSeadragon }
})

// The outlines are drawn on a canvas by their own component (tested apart); here it is a stand-in that
// notes what it was given and lets a test play the part of its count.
const heartBoxes = vi.hoisted(() => ({ props: null }))
vi.mock('./HeartBoxes', () => ({
  default: (props) => {
    heartBoxes.props = props
    return null
  },
}))
const heartDialog = vi.hoisted(() => ({ props: null }))
vi.mock('./HeartDialog', () => ({
  default: (props) => {
    heartDialog.props = props
    return <div role="dialog" aria-label="An opened heart" />
  },
}))
vi.mock('openseadragon', () => ({ default: osd.OpenSeadragon }))
vi.mock('../api')

const info = {
  dzi: '/wall/wall.dzi',
  width: 200000,
  height: 2000,
  overview: '/wall/wall-overview.jpg',
  breaks: [
    { x: 30000, kind: 'seam' },
    { x: 50000, kind: 'gap', label: 'Not photographed' },
    { x: 120000, kind: 'gap' },
  ],
  segments: [
    { x: 0, width: 49000, label: 'Photographed 30 Jul – 1 Aug 2023' },
    { x: 51000, width: 149000, label: 'Photographed 20 – 21 Aug 2023' },
  ],
}

const renderWall = async () => {
  const view = render(<WallPanorama />)
  await waitFor(() => expect(osd.state.viewer).not.toBeNull())
  return view
}

const openViewer = () => act(() => osd.state.handlers.open())

describe('WallPanorama', () => {
  beforeEach(() => {
    osd.state.handlers = {}
    osd.state.viewer = null
    osd.state.options = null
    heartBoxes.props = null
    heartDialog.props = null
    fetchWallInfo.mockResolvedValue(info)
    fetchHeartIndex.mockRejectedValue(Object.assign(new Error('Request failed (404)'), { status: 404 }))
  })

  it('shows a loading message, then a deep-zoom viewer of the stitched wall', async () => {
    render(<WallPanorama />)
    expect(screen.getByText('Loading the wall…')).toBeInTheDocument()

    await waitFor(() => expect(osd.state.options).not.toBeNull())
    expect(screen.queryByText('Loading the wall…')).not.toBeInTheDocument()
    const { element, ...options } = osd.state.options
    expect(element).toBe(screen.getByTestId('wall-viewer'))   // identity: deep-comparing DOM nodes is slow
    expect(options).toMatchObject({
      tileSources: '/wall/wall.dzi',
      showNavigationControl: false,
      gestureSettingsMouse: { clickToZoom: false, scrollToZoom: false },
    })
  })

  it('opens on the first section, centred with equal bars above and below', async () => {
    await renderWall()
    openViewer()

    const { viewport } = osd.state.viewer
    // aspect = 2000 / 200000 = 0.01; an 800x400 viewer keeps a 68px bar top and bottom,
    // so the wall gets the 264px between them.
    const [rect, immediately] = viewport.fitBounds.mock.calls.at(-1)
    expect(immediately).toBe(true)
    expect(rect.x).toBe(0)
    expect(rect.height).toBeCloseTo((0.01 * 400) / 264)
    expect(rect.y + rect.height / 2).toBeCloseTo(0.005)        // centred on the wall
    expect(rect.width).toBeCloseTo(rect.height * 2)
    expect(viewport.minZoomLevel).toBe(10) // a quarter of the fitted zoom
  })

  it('opens on photo 484 when the wall lists it, centred on that photo', async () => {
    fetchWallInfo.mockResolvedValue({
      ...info,
      photoTotal: 518,
      photos: [
        { x: 0, number: 1, file: 'first.jpg' },
        { x: 150000, number: 483, file: 'before.jpg' },
        { x: 160000, number: 484, file: 'chosen.jpg' },
        { x: 164000, number: 485, file: 'after.jpg' },
      ],
    })
    await renderWall()
    openViewer()

    const [rect, immediately] = osd.state.viewer.viewport.fitBounds.mock.calls.at(-1)
    expect(immediately).toBe(true)
    expect(rect.x + rect.width / 2).toBeCloseTo(162000 / 200000)     // the middle of photo 484
    expect(rect.height).toBeCloseTo((0.01 * 400) / 264)                // still fitted to the stage height
  })

  it('marks every join in the bars, and labels the stretches nobody photographed', async () => {
    await renderWall()
    openViewer()

    const overlays = osd.state.viewer.addOverlay.mock.calls.map(([o]) => o)
    expect(overlays.map((o) => o.element.className)).toEqual([
      'wall-notch wall-notch-top', 'wall-notch wall-notch-bottom',
      'wall-notch wall-notch-top', 'wall-notch wall-notch-bottom', 'wall-gap-label',
      'wall-notch wall-notch-top', 'wall-notch wall-notch-bottom', 'wall-gap-label',
    ])
    // notches sit just outside the wall (aspect 0.01): above its top, below its bottom
    expect(overlays[0].location.x).toBeCloseTo(0.15)
    expect(overlays[0].location.y).toBeLessThan(0)
    expect(overlays[1].location.y).toBeGreaterThan(0.01)
    expect(overlays.filter((o) => o.element.className === 'wall-gap-label').map((o) => o.element.textContent))
      .toEqual(['Not photographed', 'Not photographed'])
  })

  it('adds no markers when the wall has no breaks', async () => {
    fetchWallInfo.mockResolvedValue({ ...info, breaks: undefined })
    await renderWall()
    openViewer()

    expect(osd.state.viewer.addOverlay).not.toHaveBeenCalled()
  })

  it('zooms in, out and back to the fitted height', async () => {
    const user = userEvent.setup()
    await renderWall()
    openViewer()
    const { viewport } = osd.state.viewer

    await user.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect(viewport.zoomBy).toHaveBeenLastCalledWith(1.5)
    await user.click(screen.getByRole('button', { name: 'Zoom out' }))
    expect(viewport.zoomBy).toHaveBeenLastCalledWith(1 / 1.5)
    expect(viewport.applyConstraints).toHaveBeenCalledTimes(2)
    await user.click(screen.getByRole('button', { name: 'Fit height' }))
    // fits the height again around the current spot along the wall
    const [rect] = viewport.fitBounds.mock.calls.at(-1)
    expect(rect.x + rect.width / 2).toBeCloseTo(0.25)
    expect(rect.height).toBeCloseTo((0.01 * 400) / 264)
  })

  it('keeps the bars to a tenth of a tall viewer, within limits', async () => {
    await renderWall()
    const { viewport } = osd.state.viewer
    const fitAt = (height) => {
      viewport.getContainerSize.mockReturnValue({ x: 800, y: height })
      act(() => osd.state.handlers.open())
      return viewport.fitBounds.mock.calls.at(-1)[0].height
    }

    expect(fitAt(1000)).toBeCloseTo((0.01 * 1000) / 800)    // a tenth of 1000px
    expect(fitAt(2000)).toBeCloseTo((0.01 * 2000) / 1824)   // capped at 88px
    expect(fitAt(100)).toBeCloseTo((0.01 * 100) / 30)       // never less than 30% for the wall
  })

  it('walks along the wall by most of a screen width', async () => {
    const user = userEvent.setup()
    await renderWall()
    const { viewport } = osd.state.viewer

    const lastPan = () => viewport.panBy.mock.calls.at(-1)[0]

    await user.click(screen.getByRole('button', { name: 'Walk right along the wall' }))
    expect(lastPan().x).toBeCloseTo(0.04)
    expect(lastPan().y).toBe(0)
    await user.click(screen.getByRole('button', { name: 'Walk left along the wall' }))
    expect(lastPan().x).toBeCloseTo(-0.04)
  })

  it('has a big arrow at each side that walks along the wall', async () => {
    const user = userEvent.setup()
    await renderWall()
    const { viewport } = osd.state.viewer
    // somewhere in the middle of the wall, so neither arrow is resting
    viewport.getBounds.mockReturnValue({ x: 0.4, y: -0.001, width: 0.05, height: 0.0122 })
    act(() => osd.state.handlers['viewport-change']())

    const left = screen.getByRole('button', { name: 'Look further left along the wall' })
    const right = screen.getByRole('button', { name: 'Look further right along the wall' })
    expect(left).toHaveClass('side-arrow-left')
    expect(right).toHaveClass('side-arrow-right')

    await user.click(right)
    expect(viewport.panBy.mock.calls.at(-1)[0].x).toBeCloseTo(0.04)    // 80% of the view's width, like the dock
    await user.click(left)
    expect(viewport.panBy.mock.calls.at(-1)[0].x).toBeCloseTo(-0.04)
    expect(viewport.applyConstraints).toHaveBeenCalledTimes(2)
  })

  it('rests the side arrows at the two ends of the wall', async () => {
    await renderWall()
    const { viewport } = osd.state.viewer
    const left = screen.getByRole('button', { name: 'Look further left along the wall' })
    const right = screen.getByRole('button', { name: 'Look further right along the wall' })
    const viewAt = (x, width = 0.05) => {
      viewport.getBounds.mockReturnValue({ x, y: -0.001, width, height: 0.0122 })
      act(() => osd.state.handlers['viewport-change']())
    }

    viewAt(0)
    expect(left).toBeDisabled()
    expect(right).toBeEnabled()

    viewAt(0.5)
    expect(left).toBeEnabled()
    expect(right).toBeEnabled()

    viewAt(0.95)                      // the view's right edge is the wall's end
    expect(left).toBeEnabled()
    expect(right).toBeDisabled()
  })

  it('tracks and sets the position along the wall on the overview map', async () => {
    const { container } = await renderWall()
    const { viewport } = osd.state.viewer
    const slider = screen.getByRole('slider', { name: 'Position along the wall' })

    act(() => osd.state.handlers['viewport-change']())
    expect(slider).toHaveValue('250')
    const windowEl = screen.getByTestId('wall-map-window')
    expect(windowEl.style.left).toBe('20%')
    expect(parseFloat(windowEl.style.width)).toBeCloseTo(5)
    expect(container.querySelector('.wall-map').style.backgroundImage).toBe('url("/wall/wall-overview.jpg")')

    viewport.getCenter.mockReturnValue({ x: 1.3, y: 0.01 })
    act(() => osd.state.handlers['viewport-change']())
    expect(slider).toHaveValue('1000') // clamped to the end of the wall

    fireEvent.change(slider, { target: { value: '600' } })
    expect(viewport.panTo).toHaveBeenCalledWith(expect.objectContaining({ x: 0.6, y: 0.01 }), true)
  })

  it('names when each stretch was photographed, and nothing over a gap', async () => {
    await renderWall()
    const { viewport } = osd.state.viewer

    viewport.getCenter.mockReturnValue({ x: 0.1, y: 0.01 })
    act(() => osd.state.handlers['viewport-change']())
    expect(screen.getByText('Photographed 30 Jul – 1 Aug 2023')).toBeInTheDocument()

    viewport.getCenter.mockReturnValue({ x: 0.6, y: 0.01 })
    act(() => osd.state.handlers['viewport-change']())
    expect(screen.getByText('Photographed 20 – 21 Aug 2023')).toBeInTheDocument()

    viewport.getCenter.mockReturnValue({ x: 0.25, y: 0.01 })        // inside the gap
    act(() => osd.state.handlers['viewport-change']())
    expect(screen.queryByText(/^Photographed/)).not.toBeInTheDocument()
  })

  it('shows the photo at the centre of the view', async () => {
    fetchWallInfo.mockResolvedValue({
      ...info,
      photoTotal: 518,
      photos: [
        { x: 0, number: 1, file: 'first.jpg' },
        { x: 60000, number: 2, file: 'second.jpg' },
      ],
    })
    await renderWall()
    const { viewport } = osd.state.viewer

    viewport.getCenter.mockReturnValue({ x: 0.1, y: 0.01 })       // 20000 px along
    act(() => osd.state.handlers['viewport-change']())
    expect(screen.getByText(/Photo 1 of 518/)).toBeInTheDocument()
    expect(screen.getByText('first.jpg')).toBeInTheDocument()

    viewport.getCenter.mockReturnValue({ x: 0.5, y: 0.01 })
    act(() => osd.state.handlers['viewport-change']())
    expect(screen.getByText(/Photo 2 of 518/)).toBeInTheDocument()
  })

  it('copes with a wall description without segments or an overview', async () => {
    fetchWallInfo.mockResolvedValue({ ...info, segments: undefined, overview: undefined })
    const { container } = await renderWall()
    act(() => osd.state.handlers['viewport-change']())
    expect(screen.queryByText(/^Photographed/)).not.toBeInTheDocument()
    expect(container.querySelector('.wall-map').style.backgroundImage).toBe('')
    expect(screen.queryByText(/^Photo \d/)).not.toBeInTheDocument()
  })

  it('keeps the wall centred while its whole height is in view', async () => {
    await renderWall()
    const viewer = osd.state.viewer
    const { viewport } = viewer

    // drifted off-centre while fully in view: pulled back, vertical panning locked
    viewport.getCenter.mockReturnValue({ x: 0.3, y: 0.0062 })
    act(() => osd.state.handlers['viewport-change']())
    expect(viewport.panTo).toHaveBeenLastCalledWith(expect.objectContaining({ x: 0.3, y: 0.005 }), true)
    expect(viewer.panVertical).toBe(false)

    // zoomed in past the wall's height: free to pan up and down
    viewport.panTo.mockClear()
    viewport.getBounds.mockReturnValue({ x: 0.3, y: 0.002, width: 0.008, height: 0.004 })
    act(() => osd.state.handlers['viewport-change']())
    expect(viewport.panTo).not.toHaveBeenCalled()
    expect(viewer.panVertical).toBe(true)
  })

  it('walks along the wall with the wheel instead of zooming', async () => {
    await renderWall()
    const { viewport } = osd.state.viewer
    const viewer = screen.getByTestId('wall-viewer')

    // 100px of wheel on an 800px-wide viewer showing 0.05 of the wall
    const down = new WheelEvent('wheel', { deltaY: 100, bubbles: true, cancelable: true })
    viewer.dispatchEvent(down)
    expect(down.defaultPrevented).toBe(true)                  // the page does not scroll
    expect(viewport.panBy.mock.calls.at(-1)[0].x).toBeCloseTo(0.00625)
    expect(viewport.panBy.mock.calls.at(-1)[0].y).toBe(0)
    expect(viewport.zoomBy).not.toHaveBeenCalled()
    expect(viewport.applyConstraints).toHaveBeenCalled()

    // a sideways trackpad swipe walks too, and line-based wheels move further
    viewer.dispatchEvent(new WheelEvent('wheel', { deltaX: -200, deltaY: 5, bubbles: true }))
    expect(viewport.panBy.mock.calls.at(-1)[0].x).toBeCloseTo(-0.0125)
    viewer.dispatchEvent(new WheelEvent('wheel', { deltaY: 1, deltaMode: 1, bubbles: true }))
    expect(viewport.panBy.mock.calls.at(-1)[0].x).toBeCloseTo(0.001)
  })

  it('zooms about the pointer on Ctrl/⌘ + wheel, which is how a pinch arrives', async () => {
    await renderWall()
    const { viewport } = osd.state.viewer
    const viewer = screen.getByTestId('wall-viewer')

    viewer.dispatchEvent(new WheelEvent('wheel', { deltaY: -100, ctrlKey: true, clientX: 400, clientY: 200, bubbles: true }))
    const [factor, about] = viewport.zoomBy.mock.calls.at(-1)
    expect(factor).toBeCloseTo(Math.exp(0.3))
    expect(about).toEqual({ x: 0.4, y: 0.2 })                 // the point under the cursor
    expect(viewport.panBy).not.toHaveBeenCalled()

    viewer.dispatchEvent(new WheelEvent('wheel', { deltaY: 100, metaKey: true, bubbles: true }))
    expect(viewport.zoomBy.mock.calls.at(-1)[0]).toBeCloseTo(Math.exp(-0.3))
  })

  it('stops listening to the wheel when unmounted', async () => {
    const { unmount } = await renderWall()
    const viewer = screen.getByTestId('wall-viewer')
    const { viewport } = osd.state.viewer
    unmount()

    viewer.dispatchEvent(new WheelEvent('wheel', { deltaY: 100, bubbles: true }))
    expect(viewport.panBy).not.toHaveBeenCalled()
  })

  describe('the hint on how to move', () => {
    const hint = () => screen.getByText(/Scroll to walk the wall/)

    it('shows at first, and puts itself away after a few seconds', async () => {
      vi.useFakeTimers()
      try {
        render(<WallPanorama />)
        await act(() => vi.advanceTimersByTimeAsync(0))
        expect(hint()).not.toHaveClass('stage-hint-hidden')

        await act(() => vi.advanceTimersByTimeAsync(9000))
        expect(hint()).toHaveClass('stage-hint-hidden')
      } finally {
        vi.useRealTimers()
      }
    })

    it('goes as soon as the visitor presses on the wall', async () => {
      await renderWall()
      expect(hint()).not.toHaveClass('stage-hint-hidden')

      act(() => osd.state.handlers['canvas-press']())
      expect(hint()).toHaveClass('stage-hint-hidden')
    })

    it('goes as soon as the visitor uses the wheel', async () => {
      await renderWall()
      expect(hint()).not.toHaveClass('stage-hint-hidden')

      act(() => {
        screen.getByTestId('wall-viewer').dispatchEvent(new WheelEvent('wheel', { deltaY: 10, bubbles: true }))
      })
      expect(hint()).toHaveClass('stage-hint-hidden')
    })
  })

  it("tracks the wall's edges on screen for the glow behind it", async () => {
    const { container } = await renderWall()
    act(() => osd.state.handlers['viewport-change']())

    // aspect 0.01: the fake maps y to 100 + y * 10000 pixels
    const canvas = container.querySelector('.stage-canvas')
    expect(canvas.style.getPropertyValue('--wall-top')).toBe('100px')
    expect(canvas.style.getPropertyValue('--wall-bottom')).toBe('200px')
  })

  describe('full screen', () => {
    let stageRequest
    let exit
    const setFullscreenElement = (value) =>
      Object.defineProperty(document, 'fullscreenElement', { configurable: true, value })
    const goFullscreen = (stage) => {
      setFullscreenElement(stage)
      act(() => document.dispatchEvent(new Event('fullscreenchange')))
    }

    beforeEach(() => {
      stageRequest = vi.fn(() => Promise.resolve())
      exit = vi.fn(() => Promise.resolve())
      HTMLElement.prototype.requestFullscreen = stageRequest
      Object.defineProperty(document, 'fullscreenEnabled', { configurable: true, value: true })
      document.exitFullscreen = exit
      setFullscreenElement(null)
    })

    afterEach(() => {
      delete HTMLElement.prototype.requestFullscreen
      delete document.exitFullscreen
      delete document.fullscreenEnabled
      delete document.fullscreenElement
      vi.useRealTimers()
    })

    it('offers no button where the browser cannot do it', async () => {
      delete document.fullscreenEnabled
      await renderWall()
      expect(screen.queryByRole('button', { name: /full screen/ })).not.toBeInTheDocument()
    })

    it('takes the whole stage full screen, and back out again', async () => {
      const user = userEvent.setup()
      const { container } = await renderWall()
      const stage = container.querySelector('.stage')

      const enter = screen.getByRole('button', { name: 'Enter full screen' })
      expect(enter).toHaveAttribute('aria-pressed', 'false')
      await user.click(enter)
      expect(stageRequest).toHaveBeenCalledTimes(1)
      expect(stageRequest.mock.contexts[0]).toBe(stage)       // the controls come along with it

      goFullscreen(stage)
      const leave = screen.getByRole('button', { name: 'Exit full screen' })
      expect(leave).toHaveAttribute('aria-pressed', 'true')
      await user.click(leave)
      expect(exit).toHaveBeenCalledTimes(1)

      goFullscreen(null)                                         // e.g. left with Esc
      expect(screen.getByRole('button', { name: 'Enter full screen' })).toBeInTheDocument()
    })

    it('fits the wall to the new height if all of it was in view', async () => {
      const { container } = await renderWall()
      vi.useFakeTimers()                                          // after the render: waitFor needs real ones
      const { viewport } = osd.state.viewer
      viewport.getContainerSize.mockReturnValue({ x: 800, y: 400 })
      fireEvent.click(screen.getByRole('button', { name: 'Enter full screen' }))   // bounds taller than the wall

      viewport.getContainerSize.mockReturnValue({ x: 1600, y: 800 })              // the screen grew
      viewport.fitBounds.mockClear()
      goFullscreen(container.querySelector('.stage'))
      expect(viewport.fitBounds).not.toHaveBeenCalled()          // not before the screen has settled
      act(() => vi.advanceTimersByTime(150))

      const [rect] = viewport.fitBounds.mock.calls.at(-1)
      expect(rect.x + rect.width / 2).toBeCloseTo(0.25)          // around where the visitor was
      expect(rect.height).toBeCloseTo((0.01 * 800) / 624)        // 88px bars on an 800px screen
    })

    it('leaves a zoomed-in view as it is', async () => {
      const { container } = await renderWall()
      vi.useFakeTimers()
      const { viewport } = osd.state.viewer
      viewport.getBounds.mockReturnValue({ x: 0.3, y: 0.002, width: 0.008, height: 0.004 })
      fireEvent.click(screen.getByRole('button', { name: 'Enter full screen' }))

      viewport.fitBounds.mockClear()
      goFullscreen(container.querySelector('.stage'))
      act(() => vi.advanceTimersByTime(500))
      expect(viewport.fitBounds).not.toHaveBeenCalled()
    })

    it('carries on quietly when the browser refuses', async () => {
      stageRequest.mockImplementation(() => Promise.reject(new Error('Permissions check failed')))
      const user = userEvent.setup()
      await renderWall()

      await user.click(screen.getByRole('button', { name: 'Enter full screen' }))
      expect(screen.getByRole('button', { name: 'Enter full screen' })).toBeInTheDocument()
    })

    it('stops listening when unmounted', async () => {
      const { unmount, container } = await renderWall()
      vi.useFakeTimers()
      const { viewport } = osd.state.viewer
      fireEvent.click(screen.getByRole('button', { name: 'Enter full screen' }))
      const stage = container.querySelector('.stage')
      unmount()

      viewport.fitBounds.mockClear()
      setFullscreenElement(stage)
      document.dispatchEvent(new Event('fullscreenchange'))
      vi.advanceTimersByTime(500)
      expect(viewport.fitBounds).not.toHaveBeenCalled()
    })
  })

  describe('outlining the hearts', () => {
    const heartIndex = {
      dzi: info.dzi,
      photos: [
        { number: 1, file: '0001.json', x0: 0, x1: 2000 },
        { number: 2, file: '0002.json', x0: 2000, x1: 4000 },
      ],
    }
    const toggle = () => screen.findByRole('button', { name: 'Outline the hearts' })
    const count = (hearts, writing = 0, pending = false) => act(() => heartBoxes.props.onCount({ hearts, writing, pending }))

    it('offers no toggle until some photos have outlines', async () => {
      await renderWall()

      expect(screen.queryByRole('button', { name: /Outline the hearts/ })).not.toBeInTheDocument()
      expect(screen.queryByText(/A heart the computer found/)).not.toBeInTheDocument()
      expect(heartBoxes.props).toBeNull()
    })

    it('offers none for outlines made for another build of the wall, or for no photos', async () => {
      fetchHeartIndex.mockResolvedValue({ ...heartIndex, dzi: '/wall/older.dzi' })
      const { unmount } = await renderWall()
      await waitFor(() => expect(fetchHeartIndex).toHaveBeenCalled())
      expect(screen.queryByRole('button', { name: /Outline the hearts/ })).not.toBeInTheDocument()
      unmount()

      fetchHeartIndex.mockResolvedValue({ dzi: info.dzi, photos: [] })
      await renderWall()
      await waitFor(() => expect(fetchHeartIndex).toHaveBeenCalledTimes(2))
      expect(screen.queryByRole('button', { name: /Outline the hearts/ })).not.toBeInTheDocument()
    })

    it('adds a toggle that switches the outlines on and off, and explains them in the legend', async () => {
      fetchHeartIndex.mockResolvedValue(heartIndex)
      await renderWall()

      const button = await toggle()
      expect(button).toHaveAttribute('aria-pressed', 'false')
      expect(button).toHaveTextContent('Hearts') // the words go on a narrow screen, the name stays
      expect(heartBoxes.props).toMatchObject({ info, index: heartIndex, active: false, viewer: osd.state.viewer })
      expect(screen.getByText(/A heart the computer found, with writing on it/)).toBeInTheDocument()
      expect(screen.getByText(/A heart with no writing found/)).toBeInTheDocument()

      await userEvent.click(button)
      expect(button).toHaveAttribute('aria-pressed', 'true')
      expect(heartBoxes.props.active).toBe(true)

      await userEvent.click(button)
      expect(button).toHaveAttribute('aria-pressed', 'false')
      expect(heartBoxes.props.active).toBe(false)
    })

    it('puts the how-to-move hint away once the visitor reaches for the outlines', async () => {
      fetchHeartIndex.mockResolvedValue(heartIndex)
      await renderWall()
      const hint = screen.getByText(/Scroll to walk the wall/)
      expect(hint).not.toHaveClass('stage-hint-hidden')

      await userEvent.click(await toggle())
      expect(hint).toHaveClass('stage-hint-hidden')
    })

    it('says how many hearts are outlined in view, and how many have writing', async () => {
      fetchHeartIndex.mockResolvedValue(heartIndex)
      await renderWall()
      await userEvent.click(await toggle())

      count(1234, 456)
      expect(await screen.findByText(`${(1234).toLocaleString()} hearts outlined`, { exact: false })).toBeInTheDocument()
      expect(screen.getByText(`· ${(456).toLocaleString()} with writing`, { exact: false })).toBeInTheDocument()

      count(1, 1)
      expect(screen.getByText('1 heart outlined', { exact: false })).toBeInTheDocument()
    })

    it('says nothing about hearts while the outlines are off, or while the photos are still being fetched', async () => {
      fetchHeartIndex.mockResolvedValue(heartIndex)
      await renderWall()
      await toggle()
      count(5, 2)
      expect(screen.queryByText(/outlined/)).not.toBeInTheDocument() // off

      await userEvent.click(await toggle())
      count(0, 0, true)
      expect(screen.queryByText(/outlines so far/)).not.toBeInTheDocument() // the boxes are on their way
    })

    it('says where the outlines are when there are none in view, and takes the visitor there', async () => {
      fetchHeartIndex.mockResolvedValue(heartIndex)
      await renderWall()
      await userEvent.click(await toggle())
      count(0)

      expect(screen.getByText(/Only photos 1–2 have outlines so far/)).toBeInTheDocument()
      await userEvent.click(screen.getByRole('button', { name: 'Go there' }))
      const { viewport } = osd.state.viewer
      const [point] = viewport.panTo.mock.calls.at(-1)
      expect(point.x).toBeCloseTo(1000 / 200000) // the middle of the first photo's stretch (0..2000)
      expect(point.y).toBe(0.01) // at the height the visitor was looking
      expect(viewport.applyConstraints).toHaveBeenCalled()
    })

    it('speaks of a single photo in the singular', async () => {
      fetchHeartIndex.mockResolvedValue({ dzi: info.dzi, photos: [heartIndex.photos[1]] })
      await renderWall()
      await userEvent.click(await toggle())
      count(0)

      expect(screen.getByText(/Only photo 2 has outlines so far/)).toBeInTheDocument()
    })

    it('opens a heart the visitor picks, in a card over the wall, and closes it again', async () => {
      fetchHeartIndex.mockResolvedValue(heartIndex)
      await renderWall()
      await userEvent.click(await toggle())
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

      const heart = { photo: 1, number: 43, writing: true, box: { x: 100, y: 200, w: 50, h: 60 } }
      act(() => heartBoxes.props.onOpen(heart))
      expect(screen.getByRole('dialog', { name: 'An opened heart' })).toBeInTheDocument()
      expect(heartDialog.props).toMatchObject({ heart, info })

      act(() => heartDialog.props.onClose())
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })

    it('stops looking for outlines when it goes away before they arrive', async () => {
      let arrive
      fetchHeartIndex.mockReturnValue(new Promise((resolve) => (arrive = resolve)))
      const { unmount } = await renderWall()
      unmount()
      arrive(heartIndex)

      await act(async () => {})
      expect(heartBoxes.props).toBeNull()
    })
  })

  it('explains the two kinds of break', async () => {
    await renderWall()
    expect(screen.getByText(/joined without an overlap/)).toBeInTheDocument()
    expect(screen.getByText(/between visits nobody photographed/)).toBeInTheDocument()
  })

  it('destroys the viewer when unmounted', async () => {
    const { unmount } = await renderWall()
    const viewer = osd.state.viewer
    unmount()
    expect(viewer.destroy).toHaveBeenCalled()
  })

  it('explains when the stitched wall has not been built', async () => {
    fetchWallInfo.mockRejectedValue(Object.assign(new Error('Request failed (404)'), { status: 404 }))
    render(<WallPanorama />)

    expect(await screen.findByText('The stitched wall has not been built yet.')).toBeInTheDocument()
  })

  it('shows other load errors, with a generic fallback', async () => {
    fetchWallInfo.mockRejectedValue(new Error('Wall unavailable'))
    const { unmount } = render(<WallPanorama />)
    expect(await screen.findByText('Wall unavailable')).toBeInTheDocument()
    unmount()

    fetchWallInfo.mockRejectedValue(new Error(''))
    render(<WallPanorama />)
    expect(await screen.findByText('Could not load the wall.')).toBeInTheDocument()
  })
})
