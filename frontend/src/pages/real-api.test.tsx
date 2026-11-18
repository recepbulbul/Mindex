import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { api } from '@/api/client'
import { useRefreshWhenFinished } from '@/api/queries'
import type { Experiment, Timeline } from '@/api/types'
import { dataNote, usingMocks } from '@/lib/env'
import { seedExperiments } from '@/mocks/fixtures'
import { getSimulation } from '@/mocks/simulation'
import { renderApp, signIn } from '@/test/render'
import { server } from '@/test/setup'

// Screens as the real backend drives them: runs that finish in the background, start
// refusals, and the UI in real-API mode (VITE_USE_MOCKS=false).
vi.mock('@/lib/env', async (importOriginal) => {
  const env = await importOriginal<typeof import('@/lib/env')>()
  return { ...env, USING_MOCKS: false, DATA_NOTE: env.dataNote(false) }
})

const C3 = seedExperiments()[0]!

const timelineOf = (exp: Experiment): Timeline => {
  const { experimentId, days, regimes, candles, runs, trades } = getSimulation(exp)
  return { experimentId, days, regimes, candles, runs, trades }
}

describe('real-API mode', () => {
  it('reads the mode flag', () => {
    expect([usingMocks('true'), usingMocks('false'), usingMocks(undefined)]).toEqual([
      true,
      false,
      false,
    ])
    expect(dataNote(false)).toBe('geçmiş fiyat verisiyle yeniden oynatma')
  })

  it('hides the mock-only demo accounts and labels', async () => {
    renderApp('/login')
    expect(await screen.findByRole('button', { name: /Giriş yap/ })).toBeInTheDocument()
    expect(screen.queryByText('Demo hesapları')).not.toBeInTheDocument()
    expect(screen.getByText(/Kâğıt üzerinde işlem/)).toBeInTheDocument()
    expect(screen.queryByText(/Sahte API/)).not.toBeInTheDocument()
  })
})

describe('runs that finish in the background', () => {
  it('refetches everything about a run when it leaves queued/running', () => {
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const { rerender } = renderHook(
      ({ status }: { status: Experiment['status'] }) => useRefreshWhenFinished('exp-x', status),
      { wrapper, initialProps: { status: 'queued' } },
    )
    rerender({ status: 'running' })
    expect(invalidate).not.toHaveBeenCalled()
    rerender({ status: 'completed' })
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['experiments', 'exp-x'] })
  })

  it('polls a queued run until it has finished', async () => {
    let firstCall: number | null = null
    server.use(
      http.get('*/api/experiments/exp-test-c3', () => {
        firstCall ??= Date.now()
        const done = Date.now() - firstCall > 1500
        return HttpResponse.json({ ...C3, status: done ? 'completed' : 'queued' })
      }),
    )
    signIn('viewer')
    renderApp('/experiments/exp-test-c3/live')
    expect(await screen.findByText('Kuyrukta')).toBeInTheDocument()
    expect(await screen.findByText('Tamamlandı', {}, { timeout: 6000 })).toBeInTheDocument()
  }, 10_000)

  it('survives a timeline without candles for the selected asset', async () => {
    const t = timelineOf(C3)
    const { BTC: _dropped, ...rest } = t.candles
    server.use(
      http.get('*/api/experiments/exp-test-c3/timeline', () =>
        HttpResponse.json({ ...t, candles: rest }),
      ),
    )
    signIn('viewer')
    renderApp('/experiments/exp-test-c3/live')
    expect(await screen.findByText('Lider tablosu')).toBeInTheDocument()
    expect(screen.queryByText('Bir şeyler ters gitti')).not.toBeInTheDocument()
  })
})

describe('experiments list against the backend', () => {
  it('shows why a start was refused', async () => {
    signIn('researcher')
    renderApp('/experiments')
    // The seeded C1 draft runs LLM agents, which the runner refuses outside C0.
    const row = (await screen.findByText('Doğrulama · prompt ayarı')).closest('li')!
    within(row)
      .getByRole('button', { name: /Başlat/ })
      .click()
    expect(await within(row).findByRole('alert')).toHaveTextContent(/Başlatılamadı: .+/)
  })

  it('features a run without LLM agents with its best agent', async () => {
    signIn('researcher')
    const rules = await api.post<Experiment>('/experiments', {
      name: 'Yalnız kural ajanları',
      mode: 'replay',
      condition: 'C0',
      startDate: '2025-10-01',
      endDate: '2026-03-31',
      assets: ['BTC', 'ETH'],
      agentIds: ['buy-hold-btc', 'equal-weight', 'ma-cross'],
      seed: 1,
      commissionRate: 0.001,
      slippageBps: 5,
    })
    await api.post(`/experiments/${rules.id}/start`)
    const finished = await api.get<Experiment>(`/experiments/${rules.id}`)
    server.use(http.get('*/api/experiments', () => HttpResponse.json([finished])))
    renderApp('/experiments')
    expect(await screen.findByText('Sharpe oranı')).toBeInTheDocument()
    expect(screen.getByText(/ilk 3 ajan ve BTC al-tut/)).toBeInTheDocument()
  })
})

describe('agent detail against the backend', () => {
  it('ranks among the experiment’s own agents', async () => {
    signIn('viewer')
    renderApp('/experiments/exp-test-c2/agents/llm-momentum') // 8 agents; the catalogue has 9
    await waitFor(() => expect(screen.getByText(/sırada · 8 ajan/)).toBeInTheDocument())
  })
})
