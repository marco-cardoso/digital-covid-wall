import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchHeartBoxes, fetchHeartIndex, fetchInsights, fetchStats, fetchTributes, fetchWallInfo, sendFeedback } from './api'

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

  it('fetchInsights requests the insights endpoint', async () => {
    const insights = { hearts: { total: 5, with_writing: 2, photos: 1 }, per_photo: [], messages: [], relationships: [] }
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(insights))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchInsights()).resolves.toEqual(insights)
    expect(fetchMock).toHaveBeenCalledWith('/api/insights', undefined)
  })

  it('fetchHeartIndex and fetchHeartBoxes read the heart outlines that sit beside the wall', async () => {
    const index = { dzi: '/wall/wall.dzi', photos: [{ number: 1, file: '0001.json', x0: 0, x1: 2000 }] }
    const boxes = { photo: 1, hearts: [[1, 2, 3, 4, 1, 5]] }
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(index)).mockResolvedValueOnce(jsonResponse(boxes))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchHeartIndex()).resolves.toEqual(index)
    await expect(fetchHeartBoxes('0001.json')).resolves.toEqual(boxes)
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/wall/hearts/index.json', undefined)
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/wall/hearts/0001.json', undefined)
  })

  it('sendFeedback posts the message as JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }, 201))
    vi.stubGlobal('fetch', fetchMock)
    const feedback = { kind: 'typo', name: 'Ada', message: 'Fix it', contact: '', website: '' }

    await expect(sendFeedback(feedback)).resolves.toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledWith('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(feedback),
    })
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
