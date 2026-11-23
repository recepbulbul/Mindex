// API contract shared by the MSW mock and (from P5) the FastAPI backend.
// In P4 these are generated from OpenAPI; keep names aligned with docs/06-data-dictionary.md.

export const ASSETS = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP'] as const
export type Asset = (typeof ASSETS)[number]

export const CONDITIONS = ['C0', 'C1', 'C1_NO_REGIME', 'C2', 'C3'] as const
export type Condition = (typeof CONDITIONS)[number]

// The decision prompt the server stamps on new experiments (agents/llm.py `PROMPT_VERSION`).
// `decision-v4` adds the forum in C2/C3 with absolute sender weights (#57) and is
// `decision-v2` byte for byte elsewhere, as is `decision-v3` (whose per-asset shares made a
// lone post weigh 1; C2/C3 stored with it are refused). v1 (the C0 baseline), v2 and v3 stay
// runnable outside the forum for experiments stored with them.
export const PROMPT_VERSION = 'decision-v4'

export const CONDITION_LABELS: Record<Condition, string> = {
  C0: 'C0 · Hafızasız',
  C1: 'C1 · Kişisel hafıza',
  C1_NO_REGIME: 'C1′ · Rejimsiz hafıza',
  C2: 'C2 · Düz forum',
  C3: 'C3 · Güven ağırlıklı forum',
}

export type UserRole = 'researcher' | 'viewer'
export type ExperimentMode = 'replay' | 'live'
export type ExperimentStatus = 'draft' | 'queued' | 'running' | 'paused' | 'completed' | 'failed'
export type AgentKind = 'rule' | 'rl' | 'llm' | 'external'
export type Regime = 'bull' | 'bear' | 'sideways'
export type Stance = 'bullish' | 'bearish' | 'neutral'

// GET /auth/me returns the signed-in user.
export interface User {
  email: string
  role: UserRole
}

export interface LoginRequest {
  email: string
  password: string
}

// POST /auth/register (201): self sign-up always creates a viewer; 409 + fields.email when taken.
// Password is 8–128 characters; researchers are created only with `mindex create-user`.
export interface RegisterRequest {
  email: string
  password: string
}

// Returned by both POST /auth/login and POST /auth/register.
export interface LoginResponse {
  token: string
  user: User
}

export interface Agent {
  id: string
  name: string
  kind: AgentKind
  persona: string | null
  // false: this server cannot run the agent (no trained PPO model; MCP guests). It stays
  // selectable, the form warns, and create/start answer 422.
  available: boolean
}

export interface Experiment {
  id: string
  name: string
  mode: ExperimentMode
  condition: Condition
  status: ExperimentStatus
  startDate: string
  endDate: string | null
  assets: Asset[]
  agentIds: string[]
  seed: number
  commissionRate: number
  slippageBps: number
  modelVersion: string
  promptVersion: string
  createdAt: string
  error?: string | null // why the last run failed (status "failed"); a new start clears it
  studyId?: string | null // the study it belongs to, if any
}

// Experiment management (F2). Reads need a session and are open to every user; creating needs
// the researcher role, and PATCH / DELETE / start only the experiment's owner (403 otherwise).
// POST /experiments (201): validated like `experimentCreateSchema`, and a period that touches
//   the sealed test window (`TEST_WINDOW`) is refused with 422 + fields.startDate/endDate.
//   So is the PPO agent (422 + fields.agentIds) on a server without a trained PPO model,
//   on create, PATCH and import alike, so a run never fails half-way for it.
//   The server stamps `modelVersion` / `promptVersion` with what it will run.
// POST /experiments/:id/start: LLM agents run in every condition. C0 has no memory;
//   C1 / C1_NO_REGIME / C2 / C3 recall the agent's own lessons before each decision and write
//   post-mortem lessons when a position closes; C2 / C3 add the forum (`decision-v4`): posts of
//   the previous days, weighted equally (C2) or by the reader's Beta trust in the sender (C3).
//   A run recalls only lessons learned on an earlier day; each decision's recalled
//   lessons come back as `Decision.memories`, the forum posts it read as `forumMessageIds`.
//   An experiment stored with an older prompt is refused with 422 + fields.promptVersion when
//   that prompt cannot serve its condition (decision-v1 has no memory, only v4 has the forum).
// PATCH /experiments/:id (200, ExperimentUpdate): drafts only (409 otherwise); the merged
//   configuration is validated as a whole, with the same rules as create.
// DELETE /experiments/:id (204): draft, completed or failed only (409 while queued/running/paused).
// GET /experiments/:id/export.yaml: the configuration as YAML (`application/yaml`).
// POST /experiments/import (201): that YAML as the body (`Content-Type: application/yaml`)
//   creates a new draft; `llm.*` in the file is informational, the server stamps its own.
export type ExperimentCreate = Pick<
  Experiment,
  | 'name'
  | 'mode'
  | 'condition'
  | 'startDate'
  | 'endDate'
  | 'assets'
  | 'agentIds'
  | 'seed'
  | 'commissionRate'
  | 'slippageBps'
>

export type ExperimentUpdate = Partial<ExperimentCreate>

export interface Candle {
  time: string // YYYY-MM-DD (UTC)
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface Trade {
  id: string
  agentId: string
  day: string
  asset: Asset
  side: 'buy' | 'sell'
  quantity: number
  price: number
  fee: number
}

export interface EquityPoint {
  day: string
  equity: number
}

export interface AgentRun {
  agent: Agent
  equity: EquityPoint[]
  weights: Partial<Record<Asset, number>>[] // held weights per day (experiment assets)
}

// POST /experiments/:id/start (researcher): draft or failed → `queued` for the in-process
//   runner (a failed run resumes from its checkpoint, e.g. after the LLM server came back),
//   which commits each day's decisions, trades and snapshots with a checkpoint and resumes from it
//   after a restart. 409 in other states; 422 + fields when the runner cannot run it yet: `mode`
//   (live, P7), `agentIds` (external MCP agents, buy-hold-btc without BTC), `promptVersion`.
// Results of a started experiment (drafts: timeline 409, the others 404):
// GET /experiments/:id/timeline: days up to the last checkpoint; `candles` has a key per
//   experiment asset (not all five). `regimes` are the labels the run decided with: the HMM's
//   (its SHA-256 is pinned in the experiment's stored config) or, without a regime model, the
//   placeholder 'sideways' on every day (stored as `regime_source: "placeholder"`).
// GET /experiments/:id/report: 409 before the first checkpoint; `conditions` is the study's
//   comparison for an experiment in a study (once one of its runs completed), [] otherwise.
// GET /experiments/:id/forum: C2/C3 runs' posts (newest first), the current trust matrix and its
//   history; empty lists in other conditions. A post written on day t is read from t+1 on and
//   judged on the close of t+5 (`verified`, null until then and for neutral stances); posts the
//   injection filter flags are kept for the record and never shown to an agent. `content` is
//   stored sanitised and anonymised (ASSET_A…), at most 280 characters.
// GET /experiments/:id/memories?regime=&agent=&q=: most important first.
export interface Timeline {
  experimentId: string
  days: string[]
  regimes: Regime[]
  candles: Partial<Record<Asset, Candle[]>> // one key per experiment asset
  runs: AgentRun[]
  trades: Trade[]
}

export interface MemoryRef {
  id: string
  score: number
}

export interface Decision {
  id: string
  agentId: string
  day: string
  targetWeights: Partial<Record<Asset, number>>
  confidence: number
  rationale: string
  regime: Regime
  attempts: number
  heldPosition: boolean
  latencyMs: number
  memories: MemoryRef[]
  forumMessageIds: string[]
}

export interface Counterfactual {
  actual: number
  skip: number
  half: number
  stopLoss: number
}

export interface Memory {
  id: string
  agentId: string
  day: string
  lesson: string
  counterfactual: Counterfactual
  regime: Regime
  importance: number
}

export interface ForumMessage {
  id: string
  senderId: string
  day: string
  content: string
  asset: Asset
  stance: Stance
  regime: Regime // the market regime of the day it was posted
  flagged: boolean
  verified: boolean | null
}

export interface TrustScore {
  trusterId: string
  trusteeId: string
  confirmed: number
  refuted: number
  score: number
}

// The start of the run, then every day on which advice was judged.
export interface TrustHistoryPoint {
  day: string
  trusteeId: string
  score: number // mean trust other agents place in trustee
}

export interface AgentDetail {
  agent: Agent
  equity: EquityPoint[]
  decisions: Decision[]
  trustGiven: TrustScore[]
  trustReceived: TrustScore[]
}

export interface AgentMetrics {
  agentId: string
  totalReturn: number
  sharpe: number
  maxDrawdown: number
  trades: number
}

// One condition of a study, over its completed runs: means over runs and LLM agents; the
// Sharpe CI is a circular block bootstrap over days (StudyComparison). `lessonConsistency`:
// share of schema-valid post-mortem lessons that passed the numeric check (null in C0).
export interface ConditionSummary {
  condition: Condition
  runs: number
  complete: boolean // every run of this condition in the study has completed
  sharpeMean: number
  sharpeCiLow: number
  sharpeCiHigh: number
  maxDrawdown: number
  totalReturn: number
  herdCorrelation: number
  lessonConsistency: number | null
}

export interface Report {
  experimentId: string
  agents: AgentMetrics[]
  benchmark: AgentMetrics
  herdCorrelation: number
  conditions: ConditionSummary[]
}

// GET /health: liveness plus database reachability; 503 when degraded (P4).
export interface Health {
  status: 'ok' | 'degraded'
  database: boolean
}

export interface ApiErrorBody {
  detail: string
  fields?: Record<string, string>
}

// Studies (#54): one comparison of the conditions. A study is the experiments that share a
// period, agents, assets and costs: every condition (CONDITIONS) × every seed, created and
// queued together. Reads need a session; create and start need the researcher role (start:
// the study's owner). The period may not touch the sealed test window (422 + fields), and the
// agents must include an LLM agent (the comparison is about them).
// POST /studies (201): `smoke` cuts the period to SMOKE_DAYS days from `startDate` and keeps
//   only the first seed: a short check of every condition before the full run.
// POST /studies/:id/start: queues every draft or failed run (seed by seed, all conditions of
//   a seed first); 422 + fields when the runner cannot run them.
// GET /studies/:id/comparison: per condition over its completed runs; 409 before any run of
//   the study has completed. `Report.conditions` of a study's experiment is this table.
export const SMOKE_DAYS = 14
export const MAX_SEEDS = 10

export interface StudyCreate {
  name: string
  startDate: string
  endDate: string
  assets: Asset[]
  agentIds: string[]
  seeds: number[] // distinct, 1..MAX_SEEDS of them
  smoke: boolean
  commissionRate: number
  slippageBps: number
}

export interface StudyRun {
  experimentId: string
  condition: Condition
  seed: number
  status: ExperimentStatus
  lastDay: string | null // the last checkpointed day
}

export interface Study extends StudyCreate {
  id: string
  // draft: nothing started · queued/running: some run is · failed: a run failed and none is
  // active · completed: every run completed.
  status: ExperimentStatus
  createdAt: string
  runs: StudyRun[] // seed, then condition (CONDITIONS order)
}

// Difference of the mean Sharpe of LLM agents, `condition` − `baseline`, with its block-
// bootstrap 95% CI (the same resampled days for both conditions).
// Computed only over the seeds both conditions have completed (`seeds` of them); a pair
// without a common completed seed is left out.
export interface ConditionDifference {
  condition: Condition
  baseline: Condition
  seeds: number
  sharpeDiff: number
  ciLow: number
  ciHigh: number
}

export interface StudyComparison {
  studyId: string
  complete: boolean // every run of the study has completed
  days: number // daily returns per run that were compared
  blockLength: number // circular block bootstrap: block length in days ...
  resamples: number // ... and number of resamples (seeded, so the CI is reproducible)
  conditions: ConditionSummary[] // conditions with at least one completed run
  differences: ConditionDifference[] // C1−C0, C1−C1′, C2−C1, C3−C2, C3−C0 with a common seed
}
