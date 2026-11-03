import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchWallInfo } from '../api'
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
    fetchWallInfo.mockResolvedValue(info)
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
      cooperativeGestures: true,
    })
  })

  it('opens on the first section, centred with equal bars above and below', async () => {
    await renderWall()
    openViewer()

    const { viewport } = osd.state.viewer
    // aspect = 2000 / 200000 = 0.01; the wall fills 82% of a 800x400 viewer's height.
    const [rect, immediately] = viewport.fitBounds.mock.calls.at(-1)
    expect(immediately).toBe(true)
    expect(rect.x).toBe(0)
    expect(rect.height).toBeCloseTo(0.01 / 0.82)
    expect(rect.y + rect.height / 2).toBeCloseTo(0.005)        // centred on the wall
    expect(rect.width).toBeCloseTo((0.01 / 0.82) * 2)
    expect(viewport.minZoomLevel).toBe(10) // a quarter of the fitted zoom
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
    expect(rect.height).toBeCloseTo(0.01 / 0.82)
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
