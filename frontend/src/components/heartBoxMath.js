// Helpers for the boxes drawn around hearts on the wall.
//
// A heart's box is a row [x, y, w, h, writing, n] in full-size wall pixels: writing is 1 when
// writing was found on the heart, n is its number in its photo. A photo's rows come as one chunk,
// { number, x0, x1, rows }, where x0..x1 is the stretch of the wall the photo covers.

/** The photo numbers as ranges, for people: [1, 2, 5, 6, 7, 9] -> '1–2, 5–7, 9'. */
export function rangesText(numbers) {
  const sorted = [...new Set(numbers)].sort((a, b) => a - b)
  const parts = []
  for (let i = 0; i < sorted.length; ) {
    let j = i
    while (sorted[j + 1] === sorted[j] + 1) j += 1
    parts.push(j > i ? `${sorted[i]}–${sorted[j]}` : `${sorted[i]}`)
    i = j + 1
  }
  return parts.join(', ')
}

/** Which of the index's photos reach within a view's width of the view (left..right, in wall pixels). */
export function nearView(photos, left, right) {
  const margin = right - left
  return photos.filter((photo) => photo.x1 >= left - margin && photo.x0 <= right + margin)
}

/** Every loaded box that overlaps the view (a { left, right, top, bottom } in wall pixels), as { chunk, row }. */
export function visibleRows(chunks, view) {
  const found = []
  for (const chunk of chunks) {
    if (chunk.x1 < view.left || chunk.x0 > view.right) continue
    for (const row of chunk.rows) {
      if (row[0] + row[2] < view.left || row[0] > view.right || row[1] + row[3] < view.top || row[1] > view.bottom) continue
      found.push({ chunk, row })
    }
  }
  return found
}

/** The box a point (wall pixels) lies in; where boxes overlap, the smallest, since that is the one it was aimed at. */
export function rowAt(visible, x, y) {
  let best = null
  for (const hit of visible) {
    const [bx, by, bw, bh] = hit.row
    if (x < bx || x > bx + bw || y < by || y > by + bh) continue
    if (!best || bw * bh < best.row[2] * best.row[3]) best = hit
  }
  return best
}
