import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { api, ApiError } from '@/api/client'
import type { Study, StudyComparison, StudyCreate } from '@/api/types'
import { setMockExperiment } from '@/mocks/handlers'
import { renderApp, signIn } from '@/test/render'

const BODY: StudyCreate = {
  name: 'Hocaya gösterilecek',
  startDate: '2025-10-01',
  endDate: '2026-03-31',
  assets: ['BTC', 'ETH'],
  agentIds: ['buy-hold-btc', 'llm-momentum', 'llm-risk-averse'],
  seeds: [1, 2],
  smoke: false,
  commissionRate: 0.001,
  slippageBps: 5,
}

const failure = (p: Promise<unknown>) =>
  p.then(
    () => {
      throw new Error('expected a failure')
    },
    (e: unknown) => e as ApiError,
  )

describe('studies in the mock (contract of /studies)', () => {
  it('creates every condition for every seed, and smoke cuts it down', async () => {
    signIn('researcher')
    const full = await api.post<Study>('/studies', BODY)
    expect(full.runs.map((r) => `${r.seed}:${r.condition}`)).toEqual([
      '1:C0',
      '1:C1',
      '1:C1_NO_REGIME',
      '1:C2',
      '1:C3',
      '2:C0',
      '2:C1',
      '2:C1_NO_REGIME',
      '2:C2',
      '2:C3',
    ])
    expect(full.status).toBe('draft')
    const smoke = await api.post<Study>('/studies', { ...BODY, smoke: true, seeds: [7, 8] })
    expect(smoke.seeds).toEqual([7])
    expect(smoke.endDate).toBe('2025-10-15')
    expect(smoke.runs).toHaveLength(5)
  })

  it('refuses the sealed test window, studies without LLM agents and viewers', async () => {
    signIn('researcher')
    const sealed = await failure(
      api.post('/studies', { ...BODY, startDate: '2026-03-01', endDate: '2026-05-01' }),
    )
    expect(sealed).toMatchObject({
      status: 422,
      fields: { endDate: expect.stringMatching(/test/) },
    })
    const rules = await failure(
      api.post('/studies', { ...BODY, agentIds: ['buy-hold-btc', 'equal-weight'] }),
    )
    expect(rules).toMatchObject({ status: 422, fields: { agentIds: expect.stringMatching(/LLM/) } })
    signIn('viewer')
    expect(await failure(api.post('/studies', BODY))).toMatchObject({ status: 403 })
  })

  it('compares the conditions once runs have completed', async () => {
    signIn('researcher')
    const study = await api.post<Study>('/studies', BODY)
    expect(await failure(api.get(`/studies/${study.id}/comparison`))).toMatchObject({
      status: 409,
    })
    await api.post(`/studies/${study.id}/start`)
    const comparison = await api.get<StudyComparison>(`/studies/${study.id}/comparison`)
    expect(comparison.complete).toBe(true)
    expect(comparison.conditions.map((c) => [c.condition, c.runs])).toEqual([
      ['C0', 2],
      ['C1', 2],
      ['C1_NO_REGIME', 2],
      ['C2', 2],
      ['C3', 2],
    ])
    expect(comparison.conditions.map((c) => c.meanForumWeight)).toEqual([
      null,
      null,
      null,
      0.5,
      0.56,
    ])
    expect(comparison.differences.map((d) => `${d.condition}-${d.baseline}`)).toEqual([
      'C1-C0',
      'C1-C1_NO_REGIME',
      'C2-C1',
      'C3-C2',
      'C3-C0',
    ])
    // The report of each of its experiments shows the study's table (#14).
    const report = await api.get<{ conditions: unknown }>(
      `/experiments/${study.runs[0]!.experimentId}/report`,
    )
    expect(report.conditions).toEqual(comparison.conditions)
  })
})

describe('study screens (#14)', () => {
  it('creates a smoke study, starts it and shows the comparison', async () => {
    signIn('researcher')
    const { user } = renderApp('/studies')
    expect(await screen.findByText('Henüz çalışma yok')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /5 deney oluştur/ }))
    // The study screen: a grid of five drafts, then a start.
    expect(
      await screen.findByRole('heading', { name: 'C0–C3 karşılaştırması' }),
    ).toBeInTheDocument()
    expect(screen.getByText('smoke')).toBeInTheDocument()
    expect(
      screen.getByText('0/5 tamamlandı. Her hücre bir deney; tıklayınca canlı ekranı açılır.'),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Başlat/ }))
    expect(await screen.findByText(/Koşul karşılaştırması \(5 koşul, 5 koşu\)/)).toBeInTheDocument()
    const diffs = screen.getByText('Koşul farkları').closest('section')!
    expect(within(diffs).getByText('güven ağırlığı')).toBeInTheDocument()
    expect(within(diffs).getByText('hepsi birlikte')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Başlat/ })).not.toBeInTheDocument()
  })

  it('lists studies for viewers without the create form', async () => {
    signIn('researcher')
    await api.post<Study>('/studies', { ...BODY, smoke: true })
    signIn('viewer')
    renderApp('/studies')
    const list = await screen.findByRole('list', { name: 'Çalışmalar' })
    expect(within(list).getByText('Hocaya gösterilecek')).toBeInTheDocument()
    expect(within(list).getByText('0/5 koşu tamamlandı')).toBeInTheDocument()
    expect(screen.queryByText('Yeni çalışma')).not.toBeInTheDocument()
  })

  it('shows why a study could not be created', async () => {
    signIn('researcher')
    const { user } = renderApp('/studies')
    const name = await screen.findByLabelText('Ad')
    await user.clear(name)
    await user.type(name, 'x')
    await user.click(screen.getByRole('button', { name: /deney oluştur/ }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/En az 3 karakter/))
  })

  it('links a study experiment’s report to its study', async () => {
    signIn('researcher')
    const study = await api.post<Study>('/studies', { ...BODY, smoke: true })
    await api.post(`/studies/${study.id}/start`)
    renderApp(`/experiments/${study.runs[4]!.experimentId}/report`)
    const link = await screen.findByRole('link', { name: /Bu deneyin çalışması/ })
    expect(link).toHaveAttribute('href', `/studies/${study.id}`)
    expect(screen.getByText(/Koşul karşılaştırması \(5 koşul, 5 koşu\)/)).toBeInTheDocument()
  })
})

describe('an incomplete study gives no verdict (#58 review)', () => {
  it('pairs only common seeds and shows "eksik" instead of a verdict', async () => {
    signIn('researcher')
    const study = await api.post<Study>('/studies', BODY) // seeds 1 and 2
    await api.post(`/studies/${study.id}/start`)
    const c3Seed2 = study.runs.find((r) => r.condition === 'C3' && r.seed === 2)!
    setMockExperiment(c3Seed2.experimentId, { status: 'failed' })

    const comparison = await api.get<StudyComparison>(`/studies/${study.id}/comparison`)
    expect(comparison.complete).toBe(false)
    const c3 = comparison.conditions.find((c) => c.condition === 'C3')!
    expect([c3.runs, c3.complete]).toEqual([1, false])
    const c3c0 = comparison.differences.find((d) => d.condition === 'C3' && d.baseline === 'C0')!
    expect(c3c0.seeds).toBe(1) // seed 1 only: C0's seed 2 has no C3 partner
    expect(comparison.differences.find((d) => d.condition === 'C1')!.seeds).toBe(2)

    renderApp(`/studies/${study.id}`)
    const diffs = (await screen.findByText('Koşul farkları')).closest('section')!
    const rows = within(diffs).getAllByRole('row').slice(1)
    expect(rows.every((r) => r.textContent?.endsWith('eksik'))).toBe(true)
    const table = screen.getByText(/Koşul karşılaştırması/).closest('section')!
    const c3Row = within(table).getByText('C3 · Güven ağırlıklı forum').closest('tr')!
    expect(c3Row).toHaveTextContent('(eksik)')
    expect(within(c3Row).getAllByText('eksik').length).toBeGreaterThan(0) // vs C0
  })
})
