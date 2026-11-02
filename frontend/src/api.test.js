import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchStats, fetchTributes, fetchWallInfo } from './api'

const jsonResponse = (data, status = 200) => ({
  ok: status < 400,
  status,
  json: () => Promise.resolve(data),
})

const invalidJsonResponse = (status) => ({
  ok: false,
  status,
  json: () => Promise.reject(new SyntaxError('not json')),
})

describe('api client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('fetchWallInfo returns the stitched wall description', async () => {
    const info = { dzi: '/wall/wall.dzi', width: 200000, height: 3000, gaps: [] }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(info))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchWallInfo()).resolves.toEqual(info)
    expect(fetchMock).toHaveBeenCalledWith('/wall/wall.json', undefined)
  })

  it('fetchTributes requests the tributes endpoint', async () => {
    const tributes = [{ id: 1, name: 'Elena Marchetti', candles: 12 }]
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(tributes))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchTributes()).resolves.toEqual(tributes)
    expect(fetchMock).toHaveBeenCalledWith('/api/tributes', undefined)
  })

  it('fetchStats requests the stats endpoint', async () => {
    const stats = { tributes: 3, candles: 57 }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(stats))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchStats()).resolves.toEqual(stats)
    expect(fetchMock).toHaveBeenCalledWith('/api/stats', undefined)
  })

  it('throws the API detail message on error responses', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: 'Wall unavailable' }, 503)),
    )

    await expect(fetchWallInfo()).rejects.toThrow('Wall unavailable')
  })

  it('falls back to a generic message when the error body is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(invalidJsonResponse(404)))

    await expect(fetchWallInfo()).rejects.toMatchObject({
      message: 'Request failed (404)',
      status: 404,
    })
  })

  it('falls back to a generic message when detail is not a string', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: [{ msg: 'bad' }] }, 422)),
    )

    await expect(fetchWallInfo()).rejects.toThrow('Request failed (422)')
  })
})
