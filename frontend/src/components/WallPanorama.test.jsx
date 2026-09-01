import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchWallPhotos } from '../api'
import WallPanorama from './WallPanorama'

vi.mock('../api')

const photos = [
  { file: '01-left.jpg', width: 900, height: 1200, cropRight: 100 },
  { file: '02-right.jpg', width: 900, height: 1200, cropRight: 0 },
]

const renderWithPhotos = async () => {
  const view = render(<WallPanorama />)
  await screen.findByAltText('Section 1 of the memorial wall')
  return view
}

describe('WallPanorama', () => {
  beforeEach(() => {
    fetchWallPhotos.mockResolvedValue(photos)
  })

  it('shows a loading message, then the photos side by side in order', async () => {
    render(<WallPanorama />)

    expect(screen.getByText('Loading the wall…')).toBeInTheDocument()

    const images = await screen.findAllByRole('img')
    expect(images.map((img) => img.getAttribute('src'))).toEqual([
      '/pictures/web/01-left.jpg',
      '/pictures/web/02-right.jpg',
    ])
    expect(screen.queryByText('Loading the wall…')).not.toBeInTheDocument()
  })

  it('sizes each slice to hide the area repeated by the next photo', async () => {
    const { container } = await renderWithPhotos()

    const slices = [...container.querySelectorAll('.wall-slice')]
    // 900 wide, 100px repeated by the next -> visible 800 of 1200 tall.
    expect(slices[0].style.width).toBe('calc(var(--slice-h) * 0.6666666666666666)')
    // Full-height image, no source offset, positioned at the origin.
    const img0 = slices[0].querySelector('img')
    expect(img0.style.left).toBe('calc(var(--slice-h) * 0)')
    expect(img0.style.top).toBe('calc(var(--slice-h) * 0)')
    expect(slices[1].style.width).toBe('calc(var(--slice-h) * 0.75)')
  })

  it('honors an explicit source rectangle (manual editor output)', async () => {
    fetchWallPhotos.mockResolvedValue([
      { file: 'a.jpg', width: 900, height: 1200, cropRight: 0,
        srcX: 150, srcY: 60, srcW: 600, srcH: 1000 },
    ])
    const { container } = await renderWithPhotos()

    const slice = container.querySelector('.wall-slice')
    expect(slice.style.width).toBe('calc(var(--slice-h) * 0.6)') // 600/1000
    const img = slice.querySelector('img')
    expect(img.style.height).toBe('calc(var(--slice-h) * 1.2)') // 1200/1000
    expect(img.style.left).toBe('calc(var(--slice-h) * -0.15)') // -150/1000
    expect(img.style.top).toBe('calc(var(--slice-h) * -0.06)') // -60/1000
  })

  it('shows guidance when there are no photos', async () => {
    fetchWallPhotos.mockResolvedValue([])
    render(<WallPanorama />)

    expect(await screen.findByText(/No photos yet/)).toBeInTheDocument()
  })

  it('shows the API error message when loading fails', async () => {
    fetchWallPhotos.mockRejectedValue(new Error('Wall unavailable'))
    render(<WallPanorama />)

    expect(await screen.findByText('Wall unavailable')).toBeInTheDocument()
  })

  it('falls back to a generic error message', async () => {
    fetchWallPhotos.mockRejectedValue(new Error(''))
    render(<WallPanorama />)

    expect(
      await screen.findByText('Could not load the wall photos.'),
    ).toBeInTheDocument()
  })

  it('zooms in and out, clamping and updating the strip scale', async () => {
    const user = userEvent.setup()
    const { container } = await renderWithPhotos()
    const strip = container.querySelector('.wall-strip')
    const level = () => screen.getByText(/%$/).textContent

    expect(level()).toBe('100%')
    expect(strip.style.getPropertyValue('--zoom')).toBe('1')
    // Zoom out is disabled at the minimum.
    expect(screen.getByRole('button', { name: 'Zoom out' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect(level()).toBe('150%')
    expect(strip.style.getPropertyValue('--zoom')).toBe('1.5')

    await user.click(screen.getByRole('button', { name: 'Zoom out' }))
    expect(level()).toBe('100%')
  })

  it('clamps zoom at the maximum and resets to 100%', async () => {
    const user = userEvent.setup()
    await renderWithPhotos()
    const zoomIn = screen.getByRole('button', { name: 'Zoom in' })

    for (let i = 0; i < 10; i++) await user.click(zoomIn)
    expect(screen.getByText(/%$/).textContent).toBe('400%') // ZOOM_MAX
    expect(zoomIn).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Reset' }))
    expect(screen.getByText(/%$/).textContent).toBe('100%')
    expect(screen.getByRole('button', { name: 'Reset' })).toBeDisabled()
  })

  it('zooms with Ctrl + wheel, anchored on the pointer', async () => {
    const { container } = await renderWithPhotos()
    const strip = container.querySelector('.wall-strip')

    fireEvent.wheel(strip, { deltaY: -100, ctrlKey: true, clientX: 200, clientY: 100 })
    expect(screen.getByText(/%$/).textContent).toBe('150%')

    // Wheeling the other way zooms back out.
    fireEvent.wheel(strip, { deltaY: 100, ctrlKey: true, clientX: 200, clientY: 100 })
    expect(screen.getByText(/%$/).textContent).toBe('100%')

    // A plain wheel (no modifier) must not zoom.
    fireEvent.wheel(strip, { deltaY: -100, clientX: 200, clientY: 100 })
    expect(screen.getByText(/%$/).textContent).toBe('100%')
  })

  it('renders full-frame when a photo omits cropRight', async () => {
    fetchWallPhotos.mockResolvedValue([{ file: 'a.jpg', width: 900, height: 1200 }])
    const { container } = await renderWithPhotos()
    // No cropRight and no srcRect -> the whole width is shown (900/1200).
    expect(container.querySelector('.wall-slice').style.width).toBe(
      'calc(var(--slice-h) * 0.75)',
    )
  })

  it('scrolls the strip with the arrow buttons', async () => {
    const user = userEvent.setup()
    const { container } = await renderWithPhotos()
    const strip = container.querySelector('.wall-strip')
    strip.scrollBy = vi.fn()

    await user.click(screen.getByRole('button', { name: 'Scroll the wall right' }))
    expect(strip.scrollBy).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: 'smooth' }),
    )

    await user.click(screen.getByRole('button', { name: 'Scroll the wall left' }))
    expect(strip.scrollBy).toHaveBeenCalledTimes(2)
  })

  it('pans the strip while dragging with the pointer', async () => {
    const { container } = await renderWithPhotos()
    const strip = container.querySelector('.wall-strip')
    strip.scrollLeft = 100

    fireEvent.pointerDown(strip, { clientX: 200 })
    fireEvent.pointerMove(strip, { clientX: 150 })
    expect(strip.scrollLeft).toBe(150)

    fireEvent.pointerMove(strip, { clientX: 260 })
    expect(strip.scrollLeft).toBe(40)
  })

  it('stops panning once the pointer is released or leaves', async () => {
    const { container } = await renderWithPhotos()
    const strip = container.querySelector('.wall-strip')

    // Moving without a preceding pointer-down must not pan.
    fireEvent.pointerMove(strip, { clientX: 50 })
    expect(strip.scrollLeft).toBe(0)

    fireEvent.pointerDown(strip, { clientX: 200 })
    fireEvent.pointerUp(strip)
    fireEvent.pointerMove(strip, { clientX: 100 })
    expect(strip.scrollLeft).toBe(0)

    fireEvent.pointerDown(strip, { clientX: 200 })
    fireEvent.pointerLeave(strip)
    fireEvent.pointerMove(strip, { clientX: 100 })
    expect(strip.scrollLeft).toBe(0)
  })
})
