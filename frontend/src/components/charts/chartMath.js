// Pure helpers for the dashboard's charts: grouping, scales and labels.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const DAY_MS = 24 * 60 * 60 * 1000
// Photos taken more than this many days apart belong to different visits to the wall.
const VISIT_GAP_DAYS = 5

/** Groups photos (in wall order) `size` at a time, adding up their hearts. */
export function binPhotos(photos, size) {
  const bins = []
  for (let from = 0; from < photos.length; from += size) {
    const group = photos.slice(from, from + size)
    const hearts = group.reduce((sum, p) => sum + p.hearts, 0)
    const writing = group.reduce((sum, p) => sum + p.writing, 0)
    bins.push({
      index: bins.length,
      start: from, // position of the first photo in the list
      count: group.length,
      first: group[0].number,
      last: group[group.length - 1].number,
      hearts,
      writing,
      blank: hearts - writing,
    })
  }
  return bins
}

/** A tidy step for an axis that should have about `target` ticks and cover `max`. */
export function niceStep(max, target = 4) {
  if (!(max > 0)) return 1
  const raw = max / target
  const power = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw)
  return step
}

/** Axis tick: written in full under 10,000 and compact from there (10K). */
export function formatTick(value) {
  if (value >= 10000) return `${Math.round(value / 1000)}K`
  return value.toLocaleString()
}

function parseDay(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  return Date.UTC(y, m - 1, d)
}

/** '20 – 21 Aug 2023', '30 Jul – 1 Aug 2023' or '30 Jul 2023'. */
export function formatVisit(firstIso, lastIso) {
  const [a, b] = [new Date(parseDay(firstIso)), new Date(parseDay(lastIso))]
  const day = (d) => d.getUTCDate()
  const month = (d) => MONTHS[d.getUTCMonth()]
  const year = a.getUTCFullYear()
  if (firstIso === lastIso) return `${day(a)} ${month(a)} ${year}`
  if (month(a) === month(b)) return `${day(a)} – ${day(b)} ${month(b)} ${year}`
  return `${day(a)} ${month(a)} – ${day(b)} ${month(b)} ${year}`
}

/** The visits to the wall, as runs of photos: [{ start, end, label }] with end exclusive, by position in the list. */
export function visitsOf(photos) {
  const visits = []
  photos.forEach((p, i) => {
    if (!p.date) return
    const last = visits[visits.length - 1]
    if (last && parseDay(p.date) - parseDay(last.lastDate) <= VISIT_GAP_DAYS * DAY_MS) {
      last.end = i + 1
      last.lastDate = p.date
    } else {
      visits.push({ start: i, end: i + 1, firstDate: p.date, lastDate: p.date })
    }
  })
  return visits.map(({ start, end, firstDate, lastDate }) => ({
    start,
    end,
    label: formatVisit(firstDate, lastDate),
  }))
}

/** '1,019 hearts' / '1 heart' */
export function heartsText(count) {
  return `${count.toLocaleString()} ${count === 1 ? 'heart' : 'hearts'}`
}

/** 'Photo 12' or 'Photos 485–488' */
export function photosText(bin) {
  return bin.first === bin.last ? `Photo ${bin.first}` : `Photos ${bin.first}–${bin.last}`
}

/** A share of a whole as text: '21.6%'; under a tenth of a percent it says so instead of printing 0%. */
export function percentText(part, whole) {
  if (!(whole > 0)) return '0%'
  const pct = (part / whole) * 100
  if (pct > 0 && pct < 0.1) return '<0.1%'
  return `${Math.round(pct * 10) / 10}%`
}

/** SVG path for a column with a rounded top and a square foot. */
export function columnPath(x, y, w, h, radius) {
  if (h <= 0 || w <= 0) return ''
  const r = Math.max(0, Math.min(radius, w / 2, h))
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`
}
