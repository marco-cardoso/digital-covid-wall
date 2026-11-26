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

export function fetchInsights() {
  return request('/api/insights')
}

export function fetchVictims() {
  return request('/api/victims')
}

// The SHA-256 of some text, in hex; null where the browser keeps it from the page (plain HTTP away from localhost).
async function sha256Hex(text) {
  const subtle = globalThis.crypto?.subtle
  if (!subtle) return null
  const digest = await subtle.digest('SHA-256', new TextEncoder().encode(text))
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

// Messages from the contact form. On the deployed site CloudFront hands /api/feedback to a Lambda that stores them
// in DynamoDB (terraform/modules/contact-api), signing the request on the way; Lambda accepts a signed POST only
// with the body's hash in x-amz-content-sha256. Locally the FastAPI backend takes them and ignores the header.
export async function sendFeedback(feedback) {
  const body = JSON.stringify(feedback)
  const hash = await sha256Hex(body)
  return request('/api/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(hash && { 'x-amz-content-sha256': hash }) },
    body,
  })
}
