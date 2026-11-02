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

export function fetchTributes() {
  return request('/api/tributes')
}

export function fetchStats() {
  return request('/api/stats')
}

export function fetchVictims() {
  return request('/api/victims')
}
