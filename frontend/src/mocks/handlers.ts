import { delay, http, HttpResponse } from 'msw'
import {
  CONDITIONS,
  MAX_SEEDS,
  PROMPT_VERSION,
  SMOKE_DAYS,
  type AgentDetail,
  type AgentMetrics,
  type ApiErrorBody,
  type Condition,
  type ConditionDifference,
  type ConditionSummary,
  type Experiment,
  type ExperimentCreate,
  type ExperimentStatus,
  type ExperimentUpdate,
  type Health,
  type LoginRequest,
  type LoginResponse,
  type RegisterRequest,
  type Report,
  type Study,
  type StudyComparison,
  type StudyCreate,
  type Timeline,
  type User,
  type UserRole,
} from '@/api/types'
import { dailyReturns, herdCorrelation, maxDrawdown, sharpeRatio } from '@/lib/metrics'
import { experimentCreateSchema, overlapsTestWindow, TEST_WINDOW } from '@/lib/schemas'
import { AGENTS, DEMO_USERS, LLM_AGENT_IDS, seedExperiments } from './fixtures'
import { getSimulation, type Simulation } from './simulation'
import { experimentToYaml, parseYaml } from './yaml'

// Paths use a wildcard origin/prefix so they match both dev ("/api") and GitHub Pages ("/<repo>/api").
const API = '*/api'

let experiments = seedExperiments()
// Who created each experiment; the seeded ones belong to the demo researcher.
let owners = new Map<string, string>()
const SEED_OWNER = 'arastirmaci@mindex.dev'
// Self sign-ups (always viewers), on top of the fixed demo accounts.
let registered: Record<string, { password: string; role: UserRole }> = {}
export const resetMockDb = () => {
  experiments = seedExperiments()
  owners = new Map()
  registered = {}
  studies = []
}

const findUser = (email: string) => DEMO_USERS[email] ?? registered[email]

// The e-mail rides in the mock token so GET /auth/me still works after a reload resets MSW.
const session = (user: User): LoginResponse => ({
  token: `mock.${user.role}.${btoa(user.email)}.${crypto.randomUUID()}`,
  user,
})

// Like roleOf, the mock trusts its own token instead of keeping server-side sessions.
function userOf(request: Request): User | null {
  const m = /^Bearer mock\.(researcher|viewer)\.([A-Za-z0-9+/=]+)\.[0-9a-f-]{36}$/.exec(
    request.headers.get('Authorization') ?? '',
  )
  if (!m?.[1] || !m[2]) return null
  return { email: atob(m[2]), role: m[1] as UserRole }
}

const error = (status: number, detail: string, fields?: Record<string, string>) =>
  HttpResponse.json({ detail, fields } satisfies ApiErrorBody, { status })

function roleOf(request: Request): UserRole | null {
  const m = /^Bearer mock\.(researcher|viewer)\./.exec(request.headers.get('Authorization') ?? '')
  return (m?.[1] as UserRole | undefined) ?? null
}

// The mock's "worker": start answers `queued` like the backend, and the run has finished by
// the next read (the real runner takes seconds; the UI polls until it is done).
function settleRuns() {
  for (const e of experiments) if (e.status === 'queued') e.status = 'completed'
}

function findExperiment(id: string | readonly string[] | undefined) {
  settleRuns()
  return experiments.find((e) => e.id === id)
}

/** Tests only: put an experiment in a state no mock endpoint leads to (e.g. a failed run). */
export function setMockExperiment(id: string, patch: Partial<Experiment>) {
  Object.assign(
    experiments.find((e) => e.id === id)!,
    patch,
  )
}

function metricsFor(sim: Simulation, agentId: string): AgentMetrics {
  const run = sim.runs.find((r) => r.agent.id === agentId)!
  const eq = run.equity.map((p) => p.equity)
  return {
    agentId,
    totalReturn: eq.at(-1)! / eq[0]! - 1,
    sharpe: sharpeRatio(dailyReturns(eq)),
    maxDrawdown: maxDrawdown(eq),
    trades: sim.trades.filter((t) => t.agentId === agentId).length,
  }
}

function llmHerd(sim: Simulation) {
  const series = sim.runs
    .filter((r) => r.agent.kind === 'llm')
    .map((r) =>
      r.weights.slice(1).map((w, i) => {
        const prev = r.weights[i]!
        return (
          Object.values(w).reduce((s, x) => s + x, 0) -
          Object.values(prev).reduce((s, x) => s + x, 0)
        )
      }),
    )
  return herdCorrelation(series)
}

const FORBIDDEN = 'Bu işlem için yetkiniz yok.'
const NOT_OWNER = 'Bu deney başka bir araştırmacıya ait; yalnızca sahibi değiştirebilir.'
const MAX_YAML_BYTES = 64 * 1024
const CONFIG_KEYS = new Set([
  'name',
  'mode',
  'condition',
  'startDate',
  'endDate',
  'assets',
  'agentIds',
  'seed',
  'commissionRate',
  'slippageBps',
])
// Like the backend's Numeric(6, 5) / Numeric(6, 2) columns, rounded as Python's round() does.
// Both work on the number's exact binary value: toFixed rounds that half-up, Python half-even,
// so they differ only on exact binary ties (0.125 -> 0.12 in Python). 2.675 is not a tie: its
// binary value is just below, and both give 2.67.
function round(x: number, digits: number) {
  const up = Number(x.toFixed(digits))
  if (!isExactTie(x, digits)) return up
  const down = Number((up - 10 ** -digits).toFixed(digits))
  // half-even: of the two neighbours, keep the one whose last digit is even
  return Math.round(down * 10 ** digits) % 2 === 0 ? down : up
}

/** Whether x·10^digits is exactly k + ½ (x = mantissa · 2^exponent, checked in integers). */
function isExactTie(x: number, digits: number) {
  const view = new DataView(new ArrayBuffer(8))
  view.setFloat64(0, Math.abs(x))
  const bits = view.getBigUint64(0)
  const biased = Number((bits >> 52n) & 0x7ffn)
  if (biased === 0 || biased === 0x7ff) return false // zero, subnormal, inf, NaN
  const mantissa = (bits & ((1n << 52n) - 1n)) | (1n << 52n)
  const twice = mantissa * 10n ** BigInt(digits) // 2·x·10^d = twice · 2^(exponent + 1)
  const shift = biased - 1075 + 1
  if (shift >= 0) return ((twice << BigInt(shift)) & 1n) === 1n
  const divisor = 1n << BigInt(-shift)
  return twice % divisor === 0n && (twice / divisor) % 2n === 1n
}

const isOwner = (request: Request, exp: Experiment) =>
  userOf(request)?.email === (owners.get(exp.id) ?? SEED_OWNER)

// zod strips unknown keys; the backend refuses them, and so does the mock.
function unknownFields(body: unknown): Record<string, string> | null {
  const keys = Object.keys(body ?? {}).filter((k) => !CONFIG_KEYS.has(k))
  return keys.length ? Object.fromEntries(keys.map((k) => [k, 'Bilinmeyen alan.'])) : null
}
const INVALID_CONFIG = 'Geçersiz deney yapılandırması.'
const SEALED = `Dönem test penceresiyle (${TEST_WINDOW.start} – ${TEST_WINDOW.end}) çakışıyor; test seti yalnızca nihai değerlendirmede açılır.`
const DELETABLE: Experiment['status'][] = ['draft', 'completed', 'failed']
const AGENT_IDS = new Set(AGENTS.map((a) => a.id))

// The same rules as the backend: the form schema, known and distinct agents, the sealed test set.
function checkConfig(
  body: unknown,
): { data: ExperimentCreate } | { fields: Record<string, string> } {
  const parsed = experimentCreateSchema.safeParse(body)
  if (!parsed.success)
    return {
      fields: Object.fromEntries(parsed.error.issues.map((i) => [i.path.join('.'), i.message])),
    }
  const v = parsed.data
  const unknown = v.agentIds.find((id) => !AGENT_IDS.has(id))
  if (unknown) return { fields: { agentIds: `Bilinmeyen ajan: ${unknown}` } }
  if (new Set(v.agentIds).size !== v.agentIds.length)
    return { fields: { agentIds: 'Aynı ajan birden fazla seçilmiş.' } }
  if (overlapsTestWindow(v.startDate, v.endDate)) {
    const field = v.endDate !== null && v.startDate < TEST_WINDOW.start ? 'endDate' : 'startDate'
    return { fields: { [field]: SEALED } }
  }
  return {
    data: {
      ...v,
      commissionRate: round(v.commissionRate, 5),
      slippageBps: round(v.slippageBps, 2),
    },
  }
}

const configOf = (exp: Experiment): ExperimentCreate => ({
  name: exp.name,
  mode: exp.mode,
  condition: exp.condition,
  startDate: exp.startDate,
  endDate: exp.endDate,
  assets: exp.assets,
  agentIds: exp.agentIds,
  seed: exp.seed,
  commissionRate: exp.commissionRate,
  slippageBps: exp.slippageBps,
})

const YAML_KEYS = new Set([
  'name',
  'mode',
  'condition',
  'period',
  'assets',
  'agents',
  'seed',
  'execution',
  'llm',
])

function configFromYaml(doc: ReturnType<typeof parseYaml>): unknown {
  if (Object.keys(doc).some((k) => !YAML_KEYS.has(k))) throw new Error('bilinmeyen anahtar')
  const section = (key: string, allowed: string[]) => {
    const value = (doc[key] ?? {}) as Record<string, unknown>
    if (typeof value !== 'object' || Array.isArray(value)) throw new Error(`${key} eşleme değil`)
    if (Object.keys(value).some((k) => !allowed.includes(k))) throw new Error('bilinmeyen anahtar')
    return value
  }
  const period = section('period', ['start', 'end'])
  const execution = section('execution', ['commission_rate', 'slippage_bps'])
  section('llm', ['model', 'prompt_version'])
  return {
    name: doc.name,
    mode: doc.mode,
    condition: doc.condition,
    startDate: period.start,
    endDate: period.end ?? null,
    assets: doc.assets,
    agentIds: doc.agents,
    seed: doc.seed,
    commissionRate: execution.commission_rate,
    slippageBps: execution.slippage_bps,
  }
}

function addDraft(config: ExperimentCreate, request: Request): Experiment {
  const exp: Experiment = {
    ...config,
    id: `exp-${crypto.randomUUID().slice(0, 8)}`,
    status: 'draft',
    modelVersion: 'qwen3.5-9b-q4_k_m',
    promptVersion: PROMPT_VERSION,
    createdAt: new Date().toISOString(),
  }
  experiments.push(exp)
  owners.set(exp.id, userOf(request)?.email ?? '')
  return exp
}

// The backend runner's start-time refusals (services/runner.py `runnable_errors`). The mock
// can run PPO and stamps every experiment with the current prompt, so only the rules that
// hold everywhere are mirrored (every condition runs LLM agents since the forum, P6).

function runnableErrors(exp: Experiment): Record<string, string> | null {
  const fields: Record<string, string> = {}
  if (exp.mode === 'live') fields.mode = 'Canlı mod koşucuda henüz desteklenmiyor (İP7).'
  const problems = exp.agentIds.flatMap((id) => {
    const agent = AGENTS.find((a) => a.id === id)
    if (agent?.kind === 'external')
      return [`${id}: dış (MCP) ajanlar koşucuda henüz desteklenmiyor`]
    if (id === 'buy-hold-btc' && !exp.assets.includes('BTC'))
      return [`${id}: varlıklarda BTC olmalı`]
    return []
  })
  if (problems.length) fields.agentIds = `${problems.join('; ')}.`
  return Object.keys(fields).length ? fields : null
}

const SEEDS = [1, 2, 3, 4, 5]

// Mock aggregate over 5 seeds; the backend replaces min/max with a block-bootstrap 95% CI.
function conditionSummaries(exp: Experiment): ConditionSummary[] {
  if (!exp.agentIds.some((id) => LLM_AGENT_IDS.includes(id))) return []
  return CONDITIONS.map((condition) => {
    const perSeed = SEEDS.map((seed) => {
      const sim = getSimulation({ ...exp, id: `${exp.id}-${condition}-${seed}`, condition, seed })
      const llm = LLM_AGENT_IDS.filter((id) => exp.agentIds.includes(id)).map((id) =>
        metricsFor(sim, id),
      )
      const avg = (f: (x: AgentMetrics) => number) => llm.reduce((s, x) => s + f(x), 0) / llm.length
      return {
        sharpe: avg((x) => x.sharpe),
        mdd: avg((x) => x.maxDrawdown),
        ret: avg((x) => x.totalReturn),
        herd: llmHerd(sim),
        lessons: sim.memories.length,
      }
    })
    const mean = (f: (x: (typeof perSeed)[number]) => number) =>
      perSeed.reduce((s, x) => s + f(x), 0) / perSeed.length
    const sharpes = perSeed.map((x) => x.sharpe).sort((a, b) => a - b)
    return {
      condition,
      runs: SEEDS.length,
      sharpeMean: mean((x) => x.sharpe),
      sharpeCiLow: sharpes[0]!,
      sharpeCiHigh: sharpes.at(-1)!,
      maxDrawdown: mean((x) => x.mdd),
      totalReturn: mean((x) => x.ret),
      herdCorrelation: mean((x) => x.herd),
      lessonConsistency: condition === 'C0' ? null : 0.9 + (mean((x) => x.lessons) % 7) / 100,
    }
  })
}

// ---------------------------------------------------------------- studies (#54)
// The backend's services/study.py: every condition × seed as draft experiments, queued
// together, compared per condition. The mock's CI is the spread over seeds (min–max), not the
// backend's block bootstrap over days, so its numbers only show the shape.

let studies: (Study & { owner: string })[] = []
const STUDY_NOT_FOUND = 'Çalışma bulunamadı.'
const STUDY_NOT_OWNER = 'Bu çalışma başka bir araştırmacıya ait; yalnızca sahibi başlatabilir.'
const NEEDS_LLM = 'Çalışma en az bir LLM ajanı ister: karşılaştırma LLM ajanlarının üzerinedir.'
const DIFFERENCE_PAIRS: [Condition, Condition][] = [
  ['C1', 'C0'],
  ['C1', 'C1_NO_REGIME'],
  ['C2', 'C1'],
  ['C3', 'C2'],
  ['C3', 'C0'],
]
const CONDITION_NAME: Record<Condition, string> = {
  C0: 'C0',
  C1: 'C1',
  C1_NO_REGIME: 'C1′',
  C2: 'C2',
  C3: 'C3',
}

function studyRuns(study: Study): Experiment[] {
  settleRuns()
  const order = (c: Condition) => CONDITIONS.indexOf(c)
  return experiments
    .filter((e) => e.studyId === study.id)
    .sort((a, b) => a.seed - b.seed || order(a.condition) - order(b.condition))
}

function studyStatus(runs: Experiment[]): ExperimentStatus {
  const s = new Set(runs.map((e) => e.status))
  if (s.size === 0 || (s.size === 1 && s.has('draft'))) return 'draft'
  if (s.size === 1 && s.has('completed')) return 'completed'
  if (s.has('running')) return 'running'
  if (s.has('queued')) return 'queued'
  if (s.has('failed')) return 'failed'
  return 'running'
}

function studyOut({ owner: _owner, ...study }: Study & { owner: string }): Study {
  const runs = studyRuns(study)
  return {
    ...study,
    status: studyStatus(runs),
    runs: runs.map((e) => ({
      experimentId: e.id,
      condition: e.condition,
      seed: e.seed,
      status: e.status,
      lastDay: e.status === 'completed' ? e.endDate : null,
    })),
  }
}

function checkStudy(body: StudyCreate): Record<string, string> | null {
  if (typeof body.name !== 'string' || body.name.trim().length < 3)
    return { name: 'En az 3 karakter' }
  if (body.name.trim().length > 80) return { name: 'En fazla 80 karakter' }
  if (!Array.isArray(body.seeds) || body.seeds.length < 1 || body.seeds.length > MAX_SEEDS)
    return { seeds: `1 ile ${MAX_SEEDS} arasında seed` }
  if (new Set(body.seeds).size !== body.seeds.length) return { seeds: "Seed'ler farklı olmalı" }
  return null
}

function studyComparison(study: Study): StudyComparison | null {
  const runs = studyRuns(study)
  const done = runs.filter((e) => e.status === 'completed')
  if (done.length === 0) return null
  const llm = (e: Experiment) => LLM_AGENT_IDS.filter((id) => e.agentIds.includes(id))
  const perRun = done.map((e) => {
    const sim = getSimulation(e)
    const m = llm(e).map((id) => metricsFor(sim, id))
    const avg = (f: (x: AgentMetrics) => number) => m.reduce((s, x) => s + f(x), 0) / m.length
    return {
      exp: e,
      sharpe: avg((x) => x.sharpe),
      mdd: avg((x) => x.maxDrawdown),
      ret: avg((x) => x.totalReturn),
      herd: m.length >= 2 ? llmHerd(sim) : 0,
      days: sim.days.length - 1,
    }
  })
  const mean = (xs: number[]) => xs.reduce((s, x) => s + x, 0) / xs.length
  const conditions: ConditionSummary[] = CONDITIONS.flatMap((condition) => {
    const rows = perRun.filter((r) => r.exp.condition === condition)
    if (rows.length === 0) return []
    const sharpes = rows.map((r) => r.sharpe)
    return [
      {
        condition,
        runs: rows.length,
        sharpeMean: mean(sharpes),
        sharpeCiLow: Math.min(...sharpes),
        sharpeCiHigh: Math.max(...sharpes),
        maxDrawdown: mean(rows.map((r) => r.mdd)),
        totalReturn: mean(rows.map((r) => r.ret)),
        herdCorrelation: mean(rows.map((r) => r.herd)),
        lessonConsistency: condition === 'C0' ? null : 0.92,
      },
    ]
  })
  const bySeed = (c: Condition) =>
    new Map(perRun.filter((r) => r.exp.condition === c).map((r) => [r.exp.seed, r.sharpe]))
  const differences: ConditionDifference[] = DIFFERENCE_PAIRS.flatMap(([condition, baseline]) => {
    const a = bySeed(condition)
    const b = bySeed(baseline)
    const diffs = [...a].filter(([seed]) => b.has(seed)).map(([seed, x]) => x - b.get(seed)!)
    if (diffs.length === 0) return []
    return [
      {
        condition,
        baseline,
        sharpeDiff: mean(diffs),
        ciLow: Math.min(...diffs),
        ciHigh: Math.max(...diffs),
      },
    ]
  })
  const days = Math.min(...perRun.map((r) => r.days))
  return {
    studyId: study.id,
    complete: runs.every((e) => e.status === 'completed'),
    days,
    blockLength: Math.max(1, Math.round(Math.cbrt(days))),
    resamples: 2000,
    conditions,
    differences,
  }
}

const findStudy = (id: string | readonly string[] | undefined) => studies.find((s) => s.id === id)

const studyHandlers = [
  http.get(`${API}/studies`, async () => {
    await delay()
    return HttpResponse.json([...studies].reverse().map(studyOut))
  }),

  http.post(`${API}/studies`, async ({ request }) => {
    await delay()
    if (roleOf(request) !== 'researcher') return error(403, FORBIDDEN)
    const body = (await request.json()) as StudyCreate
    const invalid = checkStudy(body)
    if (invalid) return error(422, INVALID_CONFIG, invalid)
    const start = body.startDate
    const end = body.smoke ? minDate(body.endDate, addDays(start, SMOKE_DAYS)) : body.endDate
    const seeds = body.smoke ? body.seeds.slice(0, 1) : body.seeds
    const configs = seeds.flatMap((seed) =>
      CONDITIONS.map((condition): ExperimentCreate => ({
        name: `${body.name.trim()} · ${CONDITION_NAME[condition]} · seed ${seed}`,
        mode: 'replay',
        condition,
        startDate: start,
        endDate: end,
        assets: body.assets,
        agentIds: body.agentIds,
        seed,
        commissionRate: body.commissionRate,
        slippageBps: body.slippageBps,
      })),
    )
    const checked = checkConfig(configs[0])
    if ('fields' in checked) return error(422, INVALID_CONFIG, checked.fields)
    if (!body.agentIds.some((id) => LLM_AGENT_IDS.includes(id)))
      return error(422, INVALID_CONFIG, { agentIds: NEEDS_LLM })
    // Only the agents and the mode decide, and they are the same for every run.
    const notRunnable = runnableErrors({ ...checked.data, id: '', status: 'draft' } as Experiment)
    if (notRunnable)
      return error(422, 'Çalışmanın deneyleri bu koşucuda başlatılamaz.', notRunnable)
    const id = `study-${crypto.randomUUID().slice(0, 8)}`
    for (const config of configs) addDraft(config, request).studyId = id
    const study = {
      ...body,
      name: body.name.trim(),
      endDate: end,
      seeds,
      id,
      status: 'draft' as const,
      createdAt: new Date().toISOString(),
      runs: [],
      owner: userOf(request)?.email ?? '',
    }
    studies.push(study)
    return HttpResponse.json(studyOut(study), { status: 201 })
  }),

  http.get(`${API}/studies/:id`, async ({ params }) => {
    await delay()
    const study = findStudy(params.id)
    return study ? HttpResponse.json(studyOut(study)) : error(404, STUDY_NOT_FOUND)
  }),

  http.post(`${API}/studies/:id/start`, async ({ params, request }) => {
    await delay()
    if (roleOf(request) !== 'researcher') return error(403, FORBIDDEN)
    const study = findStudy(params.id)
    if (!study) return error(404, STUDY_NOT_FOUND)
    if (userOf(request)?.email !== study.owner) return error(403, STUDY_NOT_OWNER)
    for (const e of studyRuns(study))
      if (e.status === 'draft' || e.status === 'failed') {
        e.status = 'queued'
        e.error = null
      }
    const out = studyOut(study)
    return HttpResponse.json({ ...out, status: 'queued' satisfies ExperimentStatus })
  }),

  http.get(`${API}/studies/:id/comparison`, async ({ params }) => {
    await delay()
    const study = findStudy(params.id)
    if (!study) return error(404, STUDY_NOT_FOUND)
    const comparison = studyComparison(study)
    return comparison
      ? HttpResponse.json(comparison)
      : error(409, 'Çalışmanın henüz tamamlanan koşusu yok.')
  }),
]

function addDays(day: string, n: number) {
  const d = new Date(`${day}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

const minDate = (a: string, b: string) => (a < b ? a : b)

// A study's experiment reports its study's table, like the backend; the seeded demo runs keep
// their five virtual seeds per condition.
function reportConditions(exp: Experiment): ConditionSummary[] {
  if (exp.mode !== 'replay') return []
  const study = exp.studyId ? findStudy(exp.studyId) : undefined
  if (study) return studyComparison(study)?.conditions ?? []
  return conditionSummaries(exp)
}

export const handlers = [
  // Public, like the backend: the mock API has no database to lose.
  http.get(`${API}/health`, () =>
    HttpResponse.json({ status: 'ok', database: true } satisfies Health),
  ),

  http.post(`${API}/auth/login`, async ({ request }) => {
    await delay()
    const body = (await request.json()) as LoginRequest
    const email = body.email.toLowerCase()
    const user = findUser(email)
    if (!user || user.password !== body.password) return error(401, 'E-posta veya parola hatalı.')
    return HttpResponse.json(session({ email, role: user.role }))
  }),

  http.post(`${API}/auth/register`, async ({ request }) => {
    await delay()
    const body = (await request.json()) as RegisterRequest
    const email = body.email.toLowerCase()
    if (findUser(email)) {
      const taken = 'Bu e-posta ile kayıtlı bir hesap var.'
      return error(409, taken, { email: taken })
    }
    registered[email] = { password: body.password, role: 'viewer' }
    return HttpResponse.json(session({ email, role: 'viewer' }), { status: 201 })
  }),

  // Every route below requires a bearer token (F1).
  http.all(`${API}/*`, ({ request }) => {
    if (!roleOf(request)) return error(401, 'Oturum gerekli.')
    return undefined
  }),

  http.get(`${API}/auth/me`, ({ request }) => {
    const user = userOf(request)
    return user ? HttpResponse.json(user satisfies User) : error(401, 'Oturum gerekli.')
  }),

  http.get(`${API}/agents`, () => HttpResponse.json(AGENTS)),

  http.get(`${API}/experiments`, async () => {
    await delay()
    settleRuns()
    return HttpResponse.json(
      [...experiments].sort((a, b) => b.createdAt.localeCompare(a.createdAt)),
    )
  }),

  http.post(`${API}/experiments`, async ({ request }) => {
    await delay()
    if (roleOf(request) !== 'researcher') return error(403, FORBIDDEN)
    const body: unknown = await request.json()
    const extra = unknownFields(body)
    if (extra) return error(422, INVALID_CONFIG, extra)
    const checked = checkConfig(body)
    if ('fields' in checked) return error(422, INVALID_CONFIG, checked.fields)
    return HttpResponse.json(addDraft(checked.data, request), { status: 201 })
  }),

  http.post(`${API}/experiments/import`, async ({ request }) => {
    await delay()
    if (roleOf(request) !== 'researcher') return error(403, FORBIDDEN)
    const text = await request.text()
    if (new TextEncoder().encode(text).length > MAX_YAML_BYTES)
      return error(413, 'İstek çok büyük.')
    let body: unknown
    try {
      body = configFromYaml(parseYaml(text))
    } catch {
      return error(422, 'YAML okunamadı.', {
        body: 'Geçerli bir deney YAML dosyası olmalı.',
      })
    }
    const checked = checkConfig(body)
    if ('fields' in checked) return error(422, INVALID_CONFIG, checked.fields)
    return HttpResponse.json(addDraft(checked.data, request), { status: 201 })
  }),

  http.get(`${API}/experiments/:id`, ({ params }) => {
    const exp = findExperiment(params.id)
    return exp ? HttpResponse.json(exp) : error(404, 'Deney bulunamadı.')
  }),

  http.patch(`${API}/experiments/:id`, async ({ params, request }) => {
    await delay()
    if (roleOf(request) !== 'researcher') return error(403, FORBIDDEN)
    const exp = findExperiment(params.id)
    if (!exp) return error(404, 'Deney bulunamadı.')
    if (!isOwner(request, exp)) return error(403, NOT_OWNER)
    if (exp.status !== 'draft') return error(409, 'Yalnızca taslak deneyler düzenlenebilir.')
    const patch = (await request.json()) as ExperimentUpdate
    const extra = unknownFields(patch)
    if (extra) return error(422, INVALID_CONFIG, extra)
    const checked = checkConfig({ ...configOf(exp), ...patch })
    if ('fields' in checked) return error(422, INVALID_CONFIG, checked.fields)
    Object.assign(exp, checked.data)
    return HttpResponse.json(exp)
  }),

  http.delete(`${API}/experiments/:id`, async ({ params, request }) => {
    await delay()
    if (roleOf(request) !== 'researcher') return error(403, FORBIDDEN)
    const exp = findExperiment(params.id)
    if (!exp) return error(404, 'Deney bulunamadı.')
    if (!isOwner(request, exp)) return error(403, NOT_OWNER)
    if (!DELETABLE.includes(exp.status))
      return error(409, `"${exp.status}" durumundaki deney silinemez.`)
    experiments = experiments.filter((e) => e !== exp)
    return new HttpResponse(null, { status: 204 })
  }),

  http.post(`${API}/experiments/:id/start`, ({ params, request }) => {
    if (roleOf(request) !== 'researcher') return error(403, FORBIDDEN)
    const exp = findExperiment(params.id)
    if (!exp) return error(404, 'Deney bulunamadı.')
    if (!isOwner(request, exp)) return error(403, NOT_OWNER)
    if (exp.status !== 'draft' && exp.status !== 'failed')
      return error(409, `"${exp.status}" durumundaki deney başlatılamaz.`)
    const notRunnable = runnableErrors(exp)
    if (notRunnable) return error(422, 'Deney bu koşucuda başlatılamaz.', notRunnable)
    exp.status = 'queued'
    exp.error = null // a new start clears the previous run's error, as the backend does
    return HttpResponse.json({ ...exp })
  }),

  http.get(`${API}/experiments/:id/export.yaml`, ({ params }) => {
    const exp = findExperiment(params.id)
    if (!exp) return error(404, 'Deney bulunamadı.')
    const yaml = experimentToYaml(exp)
    return new HttpResponse(yaml, { headers: { 'Content-Type': 'application/yaml' } })
  }),

  http.get(`${API}/experiments/:id/timeline`, async ({ params }) => {
    await delay()
    const exp = findExperiment(params.id)
    if (!exp) return error(404, 'Deney bulunamadı.')
    if (exp.status === 'draft') return error(409, 'Deney henüz başlatılmadı.')
    const { experimentId, days, regimes, candles, runs, trades } = getSimulation(exp)
    return HttpResponse.json({
      experimentId,
      days,
      regimes,
      candles,
      runs,
      trades,
    } satisfies Timeline)
  }),

  http.get(`${API}/experiments/:id/agents/:agentId`, async ({ params }) => {
    await delay()
    const exp = findExperiment(params.id)
    if (!exp || exp.status === 'draft') return error(404, 'Deney bulunamadı.')
    const sim = getSimulation(exp)
    const run = sim.runs.find((r) => r.agent.id === params.agentId)
    if (!run) return error(404, 'Ajan bu deneyde yok.')
    return HttpResponse.json({
      agent: run.agent,
      equity: run.equity,
      decisions: sim.decisions.filter((d) => d.agentId === run.agent.id).reverse(),
      trustGiven: sim.trust.filter((t) => t.trusterId === run.agent.id),
      trustReceived: sim.trust.filter((t) => t.trusteeId === run.agent.id),
    } satisfies AgentDetail)
  }),

  http.get(`${API}/experiments/:id/memories`, async ({ params, request }) => {
    await delay()
    const exp = findExperiment(params.id)
    if (!exp || exp.status === 'draft') return error(404, 'Deney bulunamadı.')
    const url = new URL(request.url)
    const regime = url.searchParams.get('regime')
    const agent = url.searchParams.get('agent')
    const q = url.searchParams.get('q')?.toLocaleLowerCase('tr') ?? ''
    const items = getSimulation(exp)
      .memories.filter(
        (x) =>
          (!regime || x.regime === regime) &&
          (!agent || x.agentId === agent) &&
          (!q || x.lesson.toLocaleLowerCase('tr').includes(q)),
      )
      .sort((a, b) => b.importance - a.importance)
    return HttpResponse.json(items)
  }),

  http.get(`${API}/experiments/:id/forum`, async ({ params }) => {
    await delay()
    const exp = findExperiment(params.id)
    if (!exp || exp.status === 'draft') return error(404, 'Deney bulunamadı.')
    const { forum, trust, trustHistory } = getSimulation(exp)
    return HttpResponse.json({ messages: [...forum].reverse(), trust, trustHistory })
  }),

  http.get(`${API}/experiments/:id/report`, async ({ params }) => {
    await delay()
    const exp = findExperiment(params.id)
    if (!exp || exp.status === 'draft') return error(404, 'Deney bulunamadı.')
    const sim = getSimulation(exp)
    return HttpResponse.json({
      experimentId: exp.id,
      agents: sim.runs.map((r) => metricsFor(sim, r.agent.id)),
      benchmark: metricsFor(
        getSimulation({ ...exp, id: `${exp.id}-benchmark`, agentIds: ['buy-hold-btc'] }),
        'buy-hold-btc',
      ),
      herdCorrelation: llmHerd(sim),
      conditions: reportConditions(exp),
    } satisfies Report)
  }),
  ...studyHandlers,
]
