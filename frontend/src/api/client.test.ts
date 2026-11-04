import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { server } from '@/test/setup'
import { API_BASE, api, ApiError, setApiRecovery } from './client'

// What the dev server answers when the mock worker is not intercepting: an empty 404 for POST.
const devServer404 = () => new HttpResponse(null, { status: 404 })

describe('api client', () => {
  afterEach(() => setApiRecovery(null))

  it('recovers the API once and retries when a request never reached it', async () => {
    let calls = 0
    server.use(
      http.post(`${API_BASE}/auth/login`, () =>
        ++calls === 1 ? devServer404() : HttpResponse.json({ ok: true }),
      ),
    )
    const recover = vi.fn<() => Promise<void>>().mockResolvedValue()
    setApiRecovery(recover)

    await expect(api.post('/auth/login', {})).resolves.toEqual({ ok: true })
    expect(recover).toHaveBeenCalledOnce()
    expect(calls).toBe(2)
  })

  it('reports an unreachable API clearly instead of a JSON parse error', async () => {
    server.use(
      http.get(`${API_BASE}/experiments`, () =>
        HttpResponse.text('<!doctype html><html></html>', {
          headers: { 'Content-Type': 'text/html' },
        }),
      ),
    )
    const err = await api.get('/experiments').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).message).toMatch(/Sunucuya ulaşılamadı/)
  })
})
