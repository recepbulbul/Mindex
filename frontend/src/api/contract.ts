// Compile-time contract check: the hand-written types.ts against generated.ts (the backend's
// OpenAPI schema). `tsc -b` fails here when they drift apart; CI regenerates generated.ts and
// fails when it was not committed. Nothing in this file exists at runtime.
//
// Responses: what the backend returns must fit what the UI reads (extra fields are fine).
// Requests: what the UI sends must fit what the backend accepts.
// Enums: identical in both directions.
// Endpoints: each operation's response and body (from `paths`), not only the schemas.
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
  Expect<Fits<G.StudyOut, T.Study>>,
  Expect<Fits<G.StudyComparisonOut, T.StudyComparison>>,
]

export type RequestChecks = [
  Expect<Fits<T.LoginRequest, G.LoginRequest>>,
  Expect<Fits<T.RegisterRequest, G.RegisterRequest>>,
  Expect<Fits<T.ExperimentCreate, G.ExperimentCreate>>,
  Expect<Fits<T.StudyCreate, G.StudyCreate>>,
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

type Res = G.ApiResponses
type Body = G.ApiRequestBodies
const E = '/api/experiments/{experiment_id}'
const S = '/api/studies/{study_id}'

export type EndpointChecks = [
  Expect<Fits<Res['GET /api/health'], T.Health>>,
  Expect<Fits<Res['POST /api/auth/login'], T.LoginResponse>>,
  Expect<Fits<Res['POST /api/auth/register'], T.LoginResponse>>,
  Expect<Fits<Res['GET /api/auth/me'], T.User>>,
  Expect<Fits<Res['GET /api/agents'], T.Agent[]>>,
  Expect<Fits<Res['GET /api/experiments'], T.Experiment[]>>,
  Expect<Fits<Res['POST /api/experiments'], T.Experiment>>,
  Expect<Fits<Res['POST /api/experiments/import'], T.Experiment>>,
  Expect<Fits<Res[`GET ${typeof E}`], T.Experiment>>,
  Expect<Fits<Res[`PATCH ${typeof E}`], T.Experiment>>,
  Expect<Fits<Res[`POST ${typeof E}/start`], T.Experiment>>,
  Expect<Fits<Res[`GET ${typeof E}/timeline`], T.Timeline>>,
  Expect<Fits<Res[`GET ${typeof E}/agents/{agent_id}`], T.AgentDetail>>,
  Expect<Fits<Res[`GET ${typeof E}/report`], T.Report>>,
  Expect<Fits<Res[`GET ${typeof E}/memories`], T.Memory[]>>,
  Expect<Fits<Res[`GET ${typeof E}/forum`], ForumData>>,
  Expect<Fits<Res['GET /api/studies'], T.Study[]>>,
  Expect<Fits<Res['POST /api/studies'], T.Study>>,
  Expect<Fits<Res[`GET ${typeof S}`], T.Study>>,
  Expect<Fits<Res[`POST ${typeof S}/start`], T.Study>>,
  Expect<Fits<Res[`GET ${typeof S}/comparison`], T.StudyComparison>>,
  Expect<Fits<T.StudyCreate, Body['POST /api/studies']>>,
  Expect<Fits<T.LoginRequest, Body['POST /api/auth/login']>>,
  Expect<Fits<T.RegisterRequest, Body['POST /api/auth/register']>>,
  Expect<Fits<T.ExperimentCreate, Body['POST /api/experiments']>>,
  Expect<Fits<T.ExperimentUpdate, Body[`PATCH ${typeof E}`]>>,
  // Error envelope of every 4xx; the server leaves `fields` out instead of sending null.
  Expect<Fits<{ detail: string; fields?: NonNullable<G.ApiErrorBody['fields']> }, T.ApiErrorBody>>,
  Expect<Fits<T.ApiErrorBody, G.ApiErrorBody>>,
]
