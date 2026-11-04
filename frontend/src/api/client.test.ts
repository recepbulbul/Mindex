import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { server } from '@/test/setup'
import { API_BASE, api, ApiError, onApiUnreachable } from './client'

describe('api client', () => {
  it('turns an HTML fallback page into a clear error and signals that the API is unreachable', async () => {
    // What the dev server returns when no mock worker intercepts the request.
    server.use(
      http.get(`${API_BASE}/experiments`, () =>
        HttpResponse.text('<!doctype html><html></html>', {
          headers: { 'Content-Type': 'text/html' },
        }),
      ),
    )
    const unreachable = vi.fn<() => void>()
    const off = onApiUnreachable(unreachable)

    const err = await api.get('/experiments').catch((e: unknown) => e)
    off()

    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).message).toMatch(/Sunucuya ulaşılamadı/)
    expect(unreachable).toHaveBeenCalledOnce()
  })
})
