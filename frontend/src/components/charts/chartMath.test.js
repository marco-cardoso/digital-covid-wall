import { describe, expect, it } from 'vitest'
import {
  binPhotos,
  columnPath,
  formatTick,
  formatVisit,
  heartsText,
  niceStep,
  percentText,
  photosText,
  visitsOf,
} from './chartMath'

const photo = (number, hearts, writing, date = '2023-07-30') => ({ number, hearts, writing, date })

describe('binPhotos', () => {
  const photos = [photo(1, 10, 4), photo(2, 20, 5), photo(3, 30, 6), photo(4, 40, 7), photo(5, 50, 8)]

  it('adds up hearts in groups and keeps the photo numbers it spans', () => {
    expect(binPhotos(photos, 2)).toEqual([
      { index: 0, start: 0, count: 2, first: 1, last: 2, hearts: 30, writing: 9, blank: 21 },
      { index: 1, start: 2, count: 2, first: 3, last: 4, hearts: 70, writing: 13, blank: 57 },
      { index: 2, start: 4, count: 1, first: 5, last: 5, hearts: 50, writing: 8, blank: 42 },
    ])
  })

  it('one photo per group keeps every photo', () => {
    expect(binPhotos(photos, 1)).toHaveLength(5)
  })
})

describe('niceStep and formatTick', () => {
  it('picks a round step that covers the data in about four ticks', () => {
    expect(niceStep(1381)).toBe(500)
    expect(niceStep(80)).toBe(20)
    expect(niceStep(900)).toBe(250)
    expect(niceStep(12000)).toBe(5000)
  })

  it('has a step even with nothing to plot', () => {
    expect(niceStep(0)).toBe(1)
  })

  it('writes ticks in full under 10,000 and compact after', () => {
    expect(formatTick(1500)).toBe((1500).toLocaleString())
    expect(formatTick(9500)).toBe((9500).toLocaleString())
    expect(formatTick(10000)).toBe('10K')
    expect(formatTick(25000)).toBe('25K')
  })
})

describe('visits', () => {
  it('formats a visit as one day, a run in one month or a run across two', () => {
    expect(formatVisit('2023-07-30', '2023-07-30')).toBe('30 Jul 2023')
    expect(formatVisit('2023-08-20', '2023-08-21')).toBe('20 – 21 Aug 2023')
    expect(formatVisit('2023-07-30', '2023-08-01')).toBe('30 Jul – 1 Aug 2023')
  })

  it('groups photos taken within days of each other and starts a new visit after a long gap', () => {
    const photos = [
      photo(1, 1, 0, '2023-07-30'),
      photo(2, 1, 0, '2023-07-30'),
      photo(3, 1, 0, '2023-08-01'),
      photo(4, 1, 0, '2023-08-20'),
      photo(5, 1, 0, '2023-08-21'),
    ]
    expect(visitsOf(photos)).toEqual([
      { start: 0, end: 3, label: '30 Jul – 1 Aug 2023' },
      { start: 3, end: 5, label: '20 – 21 Aug 2023' },
    ])
  })

  it('ignores photos without a date', () => {
    expect(visitsOf([photo(1, 1, 0, ''), photo(2, 1, 0, '2023-07-30')])).toEqual([
      { start: 1, end: 2, label: '30 Jul 2023' },
    ])
  })
})

describe('labels', () => {
  it('says hearts or heart', () => {
    expect(heartsText(1)).toBe('1 heart')
    expect(heartsText(1019)).toBe(`${(1019).toLocaleString()} hearts`)
  })

  it('names a photo or a run of photos', () => {
    expect(photosText({ first: 12, last: 12 })).toBe('Photo 12')
    expect(photosText({ first: 485, last: 488 })).toBe('Photos 485–488')
  })

  it('writes a share as a percentage, and never rounds a small one to nothing', () => {
    expect(percentText(26821, 124408)).toBe('21.6%')
    expect(percentText(1, 5000)).toBe('<0.1%')
    expect(percentText(0, 10)).toBe('0%')
    expect(percentText(5, 0)).toBe('0%')
  })
})

describe('columnPath', () => {
  it('draws a column with a rounded top and a square foot', () => {
    expect(columnPath(10, 20, 8, 30, 4)).toBe('M10,50V24Q10,20 14,20H14Q18,20 18,24V50Z')
  })

  it('draws nothing for an empty column and keeps the rounding inside a short one', () => {
    expect(columnPath(0, 0, 8, 0, 4)).toBe('')
    expect(columnPath(0, 0, 0, 5, 4)).toBe('')
    // a column only 2px tall rounds by 2px at most, so the curve never pokes out of the column
    expect(columnPath(0, 0, 8, 2, 4)).toBe('M0,2V2Q0,0 2,0H6Q8,0 8,2V2Z')
  })
})
