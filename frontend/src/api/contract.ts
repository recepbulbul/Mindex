// Compile-time contract check: the hand-written types.ts against generated.ts (the backend's
// OpenAPI schema). `tsc -b` fails here when they drift apart; CI regenerates generated.ts and
// fails when it was not committed. Nothing in this file exists at runtime.
//
// Responses: what the backend returns must fit what the UI reads (extra fields are fine).
// Requests: what the UI sends must fit what the backend accepts.
// Enums: identical in both directions.
import type * as G from './generated'
import type { ForumData } from './queries'
import type * as T from './types'

type Fits<A, B> = [A] extends [B] ? true : false
type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false
type Expect<X extends true> = X

export type ResponseChecks = [
  Expect<Fits<G.UserOut, T.User>>,
  Expect<Fits<G.LoginResponse, T.LoginResponse>>,
  Expect<Fits<G.Health, T.Health>>,
  Expect<Fits<G.AgentOut, T.Agent>>,
  Expect<Fits<G.ExperimentOut, T.Experiment>>,
  Expect<Fits<G.TimelineOut, T.Timeline>>,
  Expect<Fits<G.AgentDetailOut, T.AgentDetail>>,
  Expect<Fits<G.ReportOut, T.Report>>,
  Expect<Fits<G.MemoryOut, T.Memory>>,
  Expect<Fits<G.ForumOut, ForumData>>,
]

export type RequestChecks = [
  Expect<Fits<T.LoginRequest, G.LoginRequest>>,
  Expect<Fits<T.RegisterRequest, G.RegisterRequest>>,
  Expect<Fits<T.ExperimentCreate, G.ExperimentCreate>>,
]

export type EnumChecks = [
  Expect<Same<G.Asset, T.Asset>>,
  Expect<Same<G.Condition, T.Condition>>,
  Expect<Same<G.ExperimentMode, T.ExperimentMode>>,
  Expect<Same<G.ExperimentStatus, T.ExperimentStatus>>,
  Expect<Same<G.AgentKindDb, T.AgentKind>>,
  Expect<Same<G.Regime, T.Regime>>,
  Expect<Same<G.Stance, T.Stance>>,
  Expect<Same<G.UserRole, T.UserRole>>,
]
