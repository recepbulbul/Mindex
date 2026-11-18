import { describe, expect, it } from 'vitest'
import { api, ApiError, tokenStore } from '@/api/client'
import type { Experiment, ExperimentCreate } from '@/api/types'
import { signIn } from '@/test/render'
import { experimentToYaml } from './yaml'

const CONFIG: ExperimentCreate = {
  name: 'Doğrulama · C1 · seed 2',
  mode: 'replay',
  condition: 'C1',
  startDate: '2025-10-01',
  endDate: '2026-03-31',
  assets: ['BTC', 'ETH'],
  agentIds: ['buy-hold-btc', 'llm-momentum'],
  seed: 2,
  commissionRate: 0.001,
  slippageBps: 5,
}

const create = (body: unknown) => api.post<Experiment>('/experiments', body)
const failure = (p: Promise<unknown>) => p.catch((e: unknown) => e as ApiError)

const configOf = (e: Experiment): ExperimentCreate => ({
  name: e.name,
  mode: e.mode,
  condition: e.condition,
  startDate: e.startDate,
  endDate: e.endDate,
  assets: e.assets,
  agentIds: e.agentIds,
  seed: e.seed,
  commissionRate: e.commissionRate,
  slippageBps: e.slippageBps,
})

describe('mock experiment contract (F2)', () => {
  it('refuses a period that touches the sealed test window', async () => {
    signIn('researcher')
    const err = await failure(create({ ...CONFIG, endDate: '2026-05-01' }))
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ status: 422, fields: { endDate: expect.stringMatching(/test/) } })
    const live = await failure(create({ ...CONFIG, mode: 'live', endDate: null }))
    expect(live).toMatchObject({ status: 422, fields: { startDate: expect.any(String) } })
  })

  it('refuses unknown or repeated agents', async () => {
    signIn('researcher')
    for (const agentIds of [
      ['buy-hold-btc', 'nope'],
      ['ppo', 'ppo'],
    ]) {
      const err = await failure(create({ ...CONFIG, agentIds }))
      expect(err).toMatchObject({ status: 422, fields: { agentIds: expect.any(String) } })
    }
  })

  it('patches a draft, validating the merged configuration', async () => {
    signIn('researcher')
    const exp = await create(CONFIG)
    const patched = await api.patch<Experiment>(`/experiments/${exp.id}`, { seed: 9 })
    expect(patched).toMatchObject({ ...CONFIG, seed: 9, status: 'draft' })
    const err = await failure(api.patch(`/experiments/${exp.id}`, { endDate: '2025-09-01' }))
    expect(err).toMatchObject({ status: 422, fields: { endDate: expect.any(String) } })
    const unknown = await failure(api.patch(`/experiments/${exp.id}`, { status: 'completed' }))
    expect(unknown).toMatchObject({ status: 422, fields: { status: 'Bilinmeyen alan.' } })
    const done = await failure(api.patch('/experiments/exp-test-c3', { seed: 2 }))
    expect(done).toMatchObject({ status: 409 })
  })

  it('deletes with 204, but not a running experiment', async () => {
    signIn('researcher')
    const exp = await create(CONFIG)
    await expect(api.delete(`/experiments/${exp.id}`)).resolves.toBeUndefined()
    await expect(api.get(`/experiments/${exp.id}`)).rejects.toMatchObject({ status: 404 })
    await expect(api.delete('/experiments/exp-live-c3')).rejects.toMatchObject({ status: 409 })
  })

  it('round-trips a configuration through export.yaml and import', async () => {
    signIn('researcher')
    const exp = await create({ ...CONFIG, name: 'Ad \'tırnaklı\' "çift"' })
    const yaml = await api.text(`/experiments/${exp.id}/export.yaml`)
    const imported = await api.postYaml<Experiment>('/experiments/import', yaml)
    expect(imported.id).not.toBe(exp.id)
    expect(imported.status).toBe('draft')
    expect(configOf(imported)).toEqual(configOf(exp))
  })

  it('answers 422 for a malformed YAML import', async () => {
    signIn('researcher')
    const err = await failure(api.postYaml('/experiments/import', 'name: x\nunknown: 1\n'))
    expect(err).toMatchObject({ status: 422 })
  })

  it('keeps writes to researchers', async () => {
    signIn('viewer')
    const writes = [
      () => create(CONFIG),
      () => api.patch('/experiments/exp-val-c1', { seed: 2 }),
      () => api.delete('/experiments/exp-val-c1'),
      () => api.postYaml('/experiments/import', 'name: x\n'),
    ]
    for (const write of writes) await expect(write()).rejects.toMatchObject({ status: 403 })
    await expect(api.get('/experiments/exp-val-c1')).resolves.toMatchObject({ status: 'draft' })
  })
})

// The exact text PyYAML's `safe_dump` writes for an export (backend `experiment_to_yaml`).
const BACKEND_YAML = `# Mindex deney yapılandırması (F2)
name: 'Ad: ''tırnaklı'' "çift" # yorum değil'
mode: replay
condition: C1
period:
  start: 2025-10-01
  end: 2026-03-31
assets:
- BTC
- ETH
agents:
- llm-momentum
- buy-hold-btc
seed: 2
execution:
  commission_rate: 1.0e-05
  slippage_bps: 5.0
llm:
  model: qwen3.5-9b-q4_k_m
  prompt_version: decision-v1
`

const asResearcher = (email: string) =>
  tokenStore.set(`mock.researcher.${btoa(email)}.${crypto.randomUUID()}`)

describe('mock contract alignment with the backend', () => {
  it('lets only the owner edit, delete or start an experiment', async () => {
    signIn('researcher')
    const exp = await create(CONFIG)
    asResearcher('baska@mindex.dev')
    for (const write of [
      () => api.patch(`/experiments/${exp.id}`, { seed: 3 }),
      () => api.delete(`/experiments/${exp.id}`),
      () => api.post(`/experiments/${exp.id}/start`),
      () => api.post('/experiments/exp-val-c1/start'), // seeded: the demo researcher's
    ])
      await expect(write()).rejects.toMatchObject({
        status: 403,
        message: expect.stringMatching(/sahibi/) as string,
      })
    await expect(api.get(`/experiments/${exp.id}`)).resolves.toMatchObject({ seed: 2 })
  })

  it('refuses unknown fields and impossible dates on create', async () => {
    signIn('researcher')
    const extra = await failure(create({ ...CONFIG, status: 'completed' }))
    expect(extra).toMatchObject({ status: 422, fields: { status: 'Bilinmeyen alan.' } })
    const feb30 = await failure(create({ ...CONFIG, startDate: '2025-02-30' }))
    expect(feb30).toMatchObject({ status: 422, fields: { startDate: 'Tarih YYYY-AA-GG olmalı' } })
  })

  it('rounds costs to the database scale like the backend', async () => {
    signIn('researcher')
    const exp = await create({ ...CONFIG, commissionRate: 0.000123456, slippageBps: 1.239 })
    expect([exp.commissionRate, exp.slippageBps]).toEqual([0.00012, 1.24])
    // Python's round(): ties go to the even digit (0.125 -> 0.12, 0.375 -> 0.38).
    const tie = await create({ ...CONFIG, slippageBps: 0.125 })
    expect(tie.slippageBps).toBe(0.12)
    expect((await create({ ...CONFIG, slippageBps: 0.375 })).slippageBps).toBe(0.38)
  })

  it('imports the YAML the backend exports', async () => {
    signIn('researcher')
    const imported = await api.postYaml<Experiment>('/experiments/import', BACKEND_YAML)
    expect(configOf(imported)).toEqual({
      ...CONFIG,
      name: 'Ad: \'tırnaklı\' "çift" # yorum değil',
      agentIds: ['llm-momentum', 'buy-hold-btc'],
      commissionRate: 0.00001,
    })
  })

  it('reads number-like names as text, like PyYAML', async () => {
    signIn('researcher')
    // PyYAML writes these unquoted; YAML 1.1 reads them back as text, so must the mock.
    for (const name of ['1e5', '1e-5x', '12a']) {
      const yaml = BACKEND_YAML.replace(/^name: .*$/m, `name: ${name}`)
      const imported = await api.postYaml<Experiment>('/experiments/import', yaml)
      expect(imported.name).toBe(name)
    }
    // ... and the mock's own export round-trips them.
    const exp = await create({ ...CONFIG, name: '1e5' })
    const again = await api.postYaml<Experiment>(
      '/experiments/import',
      await api.text(`/experiments/${exp.id}/export.yaml`),
    )
    expect(again.name).toBe('1e5')
  })

  it('refuses an extra nested key in an otherwise valid document', async () => {
    signIn('researcher')
    await expect(api.postYaml('/experiments/import', BACKEND_YAML)).resolves.toBeTruthy()
    const extra = BACKEND_YAML.replace('  slippage_bps: 5.0', '  slippage_bps: 5.0\n  leverage: 2')
    await expect(api.postYaml('/experiments/import', extra)).rejects.toMatchObject({ status: 422 })
  })

  it('checks nested keys and the size of an import', async () => {
    signIn('researcher')
    const nested = BACKEND_YAML.replace('  end: 2026-03-31', '  stop: 2026-03-31')
    await expect(api.postYaml('/experiments/import', nested)).rejects.toMatchObject({
      status: 422,
    })
    const huge = `${BACKEND_YAML}#${'x'.repeat(64 * 1024)}\n`
    await expect(api.postYaml('/experiments/import', huge)).rejects.toMatchObject({
      status: 413,
    })
  })

  it('writes plain decimals PyYAML reads as numbers, and the backend prompt version', async () => {
    signIn('researcher')
    const exp = await create(CONFIG)
    expect(exp.promptVersion).toBe('decision-v1')
    const yaml = experimentToYaml({ ...exp, commissionRate: 1e-7 })
    expect(yaml).toContain('  commission_rate: 0.0000001\n')
  })
})
