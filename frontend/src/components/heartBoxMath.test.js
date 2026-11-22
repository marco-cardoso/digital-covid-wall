import { describe, expect, it } from 'vitest'
import { nearView, rangesText, rowAt, visibleRows } from './heartBoxMath'

describe('rangesText', () => {
  it('folds runs of photo numbers into ranges', () => {
    expect(rangesText([1, 2])).toBe('1–2')
    expect(rangesText([1, 2, 3, 5, 6, 9])).toBe('1–3, 5–6, 9')
    expect(rangesText([4])).toBe('4')
  })

  it('does not mind order or repeats, and says nothing for no photos', () => {
    expect(rangesText([7, 5, 6, 5])).toBe('5–7')
    expect(rangesText([])).toBe('')
  })
})

describe('nearView', () => {
  const photos = [
    { number: 1, x0: 0, x1: 1000 },
    { number: 2, x0: 1000, x1: 2000 },
    { number: 3, x0: 5000, x1: 6000 },
  ]

  it('keeps the photos within a view-width of the view, so boxes are ready before they scroll in', () => {
    // a view 1000 wide at 1000..2000 reaches 0..3000
    expect(nearView(photos, 1000, 2000).map((p) => p.number)).toEqual([1, 2])
    expect(nearView(photos, 4000, 5000).map((p) => p.number)).toEqual([3])
    expect(nearView(photos, 9000, 9100)).toEqual([])
  })
})

describe('visibleRows', () => {
  const near = { number: 1, x0: 0, x1: 1000, rows: [[100, 100, 50, 50, 1, 1], [900, 100, 50, 50, 0, 2], [100, 900, 50, 50, 0, 3]] }
  const far = { number: 2, x0: 5000, x1: 6000, rows: [[5100, 100, 50, 50, 1, 1]] }

  it('lists the boxes that overlap the view, skipping whole photos that lie outside it', () => {
    const view = { left: 0, right: 500, top: 0, bottom: 500 }
    expect(visibleRows([near, far], view).map((hit) => hit.row[5])).toEqual([1])
    expect(visibleRows([near, far], view)[0].chunk).toBe(near)
  })

  it('includes a box that is only partly in view, and none that are above or below it', () => {
    expect(visibleRows([near], { left: 130, right: 300, top: 120, bottom: 300 }).map((hit) => hit.row[5])).toEqual([1])
    expect(visibleRows([near], { left: 0, right: 1000, top: 200, bottom: 400 })).toEqual([])
    expect(visibleRows([near], { left: 0, right: 1000, top: 0, bottom: 120 }).map((hit) => hit.row[5])).toEqual([1, 2])
  })
})

describe('rowAt', () => {
  const big = { row: [0, 0, 300, 300, 0, 1] }
  const small = { row: [100, 100, 50, 50, 1, 2] }

  it('finds the box a point is in', () => {
    expect(rowAt([big, small], 10, 10)).toBe(big)
    expect(rowAt([big, small], 500, 500)).toBeNull()
    expect(rowAt([], 1, 1)).toBeNull()
  })

  it('prefers the smallest where boxes overlap, whichever order they come in', () => {
    expect(rowAt([big, small], 120, 120)).toBe(small)
    expect(rowAt([small, big], 120, 120)).toBe(small)
  })
})
