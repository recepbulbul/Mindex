// API contract shared by the MSW mock and (from P5) the FastAPI backend.
// In P4 these are generated from OpenAPI; keep names aligned with docs/06-data-dictionary.md.

export const ASSETS = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP'] as const
export type Asset = (typeof ASSETS)[number]

export const CONDITIONS = ['C0', 'C1', 'C1_NO_REGIME', 'C2', 'C3'] as const
export type Condition = (typeof CONDITIONS)[number]

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
}

// Experiment management (F2). Reads need a session, writes the researcher role (403 otherwise).
// POST /experiments (201): validated like `experimentCreateSchema`, and a period that touches
//   the sealed test window (`TEST_WINDOW`) is refused with 422 + fields.startDate/endDate.
//   The server stamps `modelVersion` / `promptVersion` with what it will run.
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
  weights: Record<Asset, number>[] // target weights per day
}

// POST /experiments/:id/start (researcher): draft or paused → `queued` for the in-process runner,
//   which commits each day's decisions, trades and snapshots with a checkpoint and resumes from it
//   after a restart. 409 in other states; 422 + fields when the runner cannot run it yet: `mode`
//   (live, P7), `agentIds` (PPO without a trained model, external MCP agents, buy-hold-btc without
//   BTC), `condition` (LLM agents run only as the C0 baseline until memory/forum are wired in).
// Results of a started experiment (drafts: timeline 409, the others 404):
// GET /experiments/:id/timeline: days up to the last checkpoint; `candles` has a key per
//   experiment asset (not all five). `regimes` is the HMM label per day, or the placeholder
//   'sideways' on every day when the server has no regime model configured.
// GET /experiments/:id/report: 409 before the first checkpoint; `conditions` is [] until the
//   multi-seed comparison (P9). GET /experiments/:id/forum: empty lists until the forum (P6).
// GET /experiments/:id/memories?regime=&agent=&q=: most important first.
export interface Timeline {
  experimentId: string
  days: string[]
  regimes: Regime[]
  candles: Record<Asset, Candle[]>
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

export interface ConditionSummary {
  condition: Condition
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
