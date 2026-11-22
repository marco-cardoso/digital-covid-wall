async function request(path, options) {
  const res = await fetch(path, options)
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // keep generic message
    }
    const error = new Error(detail)
    error.status = res.status
    throw error
  }
  return res.json()
}

export function fetchWallInfo() {
  return request('/wall/wall.json')
}

// Boxes around the hearts, placed on the wall by scripts/locate_hearts.py: the index says which
// build of the wall they were made for and which photos have them, then each photo has its own file.
export function fetchHeartIndex() {
  return request('/wall/hearts/index.json')
}

export function fetchHeartBoxes(file) {
  return request(`/wall/hearts/${file}`)
}

export function fetchTributes() {
  return request('/api/tributes')
}

export function fetchStats() {
  return request('/api/stats')
}

export function fetchInsights() {
  return request('/api/insights')
}

export function fetchVictims() {
  return request('/api/victims')
}

export function sendFeedback(feedback) {
  return request('/api/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(feedback),
  })
}
