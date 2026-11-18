import { describe, expect, it } from 'vitest'
import { api, ApiError } from '@/api/client'
import type { Experiment, ExperimentCreate } from '@/api/types'
import { signIn } from '@/test/render'

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
