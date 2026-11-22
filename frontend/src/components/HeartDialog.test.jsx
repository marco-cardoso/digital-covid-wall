import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import HeartDialog from './HeartDialog'

// OpenSeadragon draws to a canvas, which jsdom lacks; stand in a recording fake.
const osd = vi.hoisted(() => {
  const state = { options: null, viewer: null, handlers: {} }
  const OpenSeadragon = vi.fn((options) => {
    state.options = options
    state.handlers = {}
    state.viewer = {
      viewport: { fitBounds: vi.fn(), zoomBy: vi.fn(), applyConstraints: vi.fn() },
      addHandler: vi.fn((name, fn) => {
        state.handlers[name] = fn
      }),
      destroy: vi.fn(),
    }
    return state.viewer
  })
  OpenSeadragon.Rect = class {
    constructor(x, y, width, height) {
      Object.assign(this, { x, y, width, height })
    }
  }
  return { state, OpenSeadragon }
})
vi.mock('openseadragon', () => ({ default: osd.OpenSeadragon }))

const info = { dzi: '/wall/wall.dzi', width: 10000, height: 1000, photoTotal: 518 }
const heart = { photo: 2, number: 43, writing: true, box: { x: 1000, y: 200, w: 100, h: 150 } }

const open = (props = {}) => {
  const onClose = vi.fn()
  const view = render(<HeartDialog heart={heart} info={info} onClose={onClose} {...props} />)
  return { ...view, onClose }
}

describe('HeartDialog', () => {
  beforeEach(() => {
    osd.state.options = null
    osd.state.viewer = null
  })

  it('names the heart, its photo and whether writing was found', () => {
    open()

    const dialog = screen.getByRole('dialog', { name: 'Heart 43' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveTextContent('Photo 2 of 518 · writing found')
  })

  it('says when no writing was found', () => {
    open({ heart: { ...heart, writing: false } })

    expect(screen.getByRole('dialog')).toHaveTextContent('Photo 2 of 518 · no writing found')
  })

  it('shows the wall in a viewer of its own, framed on the heart with some wall around it', () => {
    open()

    const { element, ...options } = osd.state.options
    expect(element).toBe(screen.getByTestId('heart-viewer'))
    expect(options).toMatchObject({ tileSources: '/wall/wall.dzi', showNavigationControl: false })

    act(() => osd.state.handlers.open())
    const [rect, immediately] = osd.state.viewer.viewport.fitBounds.mock.calls[0]
    // the longer side is 150 px, so 60 px is left around the heart: x 940..1160, y 140..410, in units of the wall's width
    expect(rect.x).toBeCloseTo(0.094)
    expect(rect.y).toBeCloseTo(0.014)
    expect(rect.width).toBeCloseTo(0.022)
    expect(rect.height).toBeCloseTo(0.027)
    expect(immediately).toBe(true)
  })

  it('zooms in and out, and comes back to the heart', async () => {
    const user = userEvent.setup()
    open()
    const { viewport } = osd.state.viewer

    await user.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect(viewport.zoomBy).toHaveBeenLastCalledWith(1.6)
    await user.click(screen.getByRole('button', { name: 'Zoom out' }))
    expect(viewport.zoomBy).toHaveBeenLastCalledWith(1 / 1.6)
    expect(viewport.applyConstraints).toHaveBeenCalledTimes(2)

    await user.click(screen.getByRole('button', { name: 'Back to the heart' }))
    const [rect, immediately] = viewport.fitBounds.mock.calls.at(-1)
    expect(rect.x).toBeCloseTo(0.094)
    expect(immediately).toBeUndefined() // glides back
  })

  it('brings the writing out when asked, and puts it back', async () => {
    const user = userEvent.setup()
    open()
    const viewer = screen.getByTestId('heart-viewer')
    const toggle = screen.getByRole('button', { name: 'Clearer writing' })
    expect(toggle).toHaveAttribute('aria-pressed', 'false')
    expect(viewer).not.toHaveClass('is-clear')

    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    expect(viewer).toHaveClass('is-clear')

    await user.click(toggle)
    expect(viewer).not.toHaveClass('is-clear')
  })

  describe('closing', () => {
    it('closes with its button, with Esc and with a click on the dimmed wall, but not with a click on the card', async () => {
      const user = userEvent.setup()
      const { onClose } = open()

      await user.click(screen.getByRole('dialog'))
      expect(onClose).not.toHaveBeenCalled()

      await user.click(screen.getByRole('button', { name: 'Close' }))
      expect(onClose).toHaveBeenCalledTimes(1)

      await user.keyboard('{Escape}')
      expect(onClose).toHaveBeenCalledTimes(2)

      await user.click(screen.getByTestId('heart-sheet'))
      expect(onClose).toHaveBeenCalledTimes(3)
    })

    it('ignores other keys', async () => {
      const user = userEvent.setup()
      const { onClose } = open()

      await user.keyboard('x{ArrowLeft}')
      expect(onClose).not.toHaveBeenCalled()
    })

    it('stops listening for Esc once it has gone, and takes its viewer with it', async () => {
      const user = userEvent.setup()
      const { onClose, unmount } = open()
      const { viewer } = osd.state
      unmount()

      expect(viewer.destroy).toHaveBeenCalled()
      await user.keyboard('{Escape}')
      expect(onClose).not.toHaveBeenCalled()
    })
  })

  describe('focus', () => {
    it('moves to the close button on opening, and back to where it was on closing', () => {
      const opener = document.createElement('button')
      document.body.append(opener)
      opener.focus()

      const { unmount } = open()
      expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()

      unmount()
      expect(opener).toHaveFocus()
      opener.remove()
    })

    it('goes round the card with Tab and Shift+Tab instead of out into the wall behind', async () => {
      const user = userEvent.setup()
      open()
      const close = screen.getByRole('button', { name: 'Close' })
      const last = screen.getByRole('button', { name: 'Clearer writing' })

      last.focus()
      await user.tab()
      expect(close).toHaveFocus()

      await user.tab({ shift: true })
      expect(last).toHaveFocus()

      // in between, Tab is left alone
      screen.getByRole('button', { name: 'Zoom in' }).focus()
      await user.tab()
      expect(screen.getByRole('button', { name: 'Back to the heart' })).toHaveFocus()
    })
  })
})
