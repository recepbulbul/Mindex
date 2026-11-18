import type { ApiErrorBody } from './types'

// Absolute so the same code works in the browser and in Node-based tests.
export const API_BASE =
  import.meta.env.VITE_API_BASE_URL ?? `${globalThis.location.origin}${import.meta.env.BASE_URL}api`

const TOKEN_KEY = 'mindex.token'

// Bearer token in sessionStorage is a deliberate choice until P8: once Caddy serves the UI and
// API from one origin, it can move to an httpOnly cookie (docs/02-architecture.md).
export const tokenStore = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (t: string) => sessionStorage.setItem(TOKEN_KEY, t),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
}

export class ApiError extends Error {
  readonly status: number
  readonly fields: Record<string, string>

  constructor(status: number, body: Partial<ApiErrorBody>) {
    super(body.detail ?? `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.fields = body.fields ?? {}
  }
}

type Listener = () => void
const unauthorizedListeners = new Set<Listener>()
export const onUnauthorized = (fn: Listener) => {
  unauthorizedListeners.add(fn)
  return () => void unauthorizedListeners.delete(fn)
}

// The API always answers with JSON (or YAML for exports). Anything else, such as the dev
// server's index.html or its empty 404, means the request never reached an API: in the
// prototype that is the mock service worker having been stopped by the browser.
// A 204 (DELETE) has no body and so no Content-Type; the dev server never answers 204.
const answeredByApi = (res: Response) =>
  res.status === 204 || /json|yaml/.test(res.headers.get('Content-Type') ?? '')

let recoverApi: (() => Promise<void>) | null = null
// Queries refetch together (e.g. when the tab regains focus), so they fail together: they share
// one recovery instead of each restarting the mock worker under the others' retries.
let recovering: Promise<void> | null = null
/** Registers how to bring the API back (the mock worker's reconnect); one retry follows. */
export const setApiRecovery = (fn: (() => Promise<void>) | null) => {
  recoverApi = fn
}

async function request(path: string, init: RequestInit = {}, retried = false): Promise<Response> {
  const headers = new Headers(init.headers)
  const token = tokenStore.get()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (!answeredByApi(res)) {
    if (recoverApi && !retried) {
      await (recovering ??= recoverApi().finally(() => (recovering = null)))
      return request(path, init, true)
    }
    throw new ApiError(503, { detail: 'Sunucuya ulaşılamadı. Sayfayı yenileyip tekrar deneyin.' })
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as Partial<ApiErrorBody>
    if (res.status === 401 && token) unauthorizedListeners.forEach((fn) => fn())
    throw new ApiError(res.status, body)
  }
  return res
}

const send = async <T>(method: string, path: string, body?: unknown) =>
  (
    await request(path, { method, body: body === undefined ? undefined : JSON.stringify(body) })
  ).json() as Promise<T>

export const api = {
  get: async <T>(path: string) => (await request(path)).json() as Promise<T>,
  text: async (path: string) => (await request(path)).text(),
  post: <T>(path: string, body?: unknown) => send<T>('POST', path, body),
  patch: <T>(path: string, body: unknown) => send<T>('PATCH', path, body),
  /** POSTs a YAML document as-is (e.g. an exported experiment configuration). */
  postYaml: async <T>(path: string, yaml: string) =>
    (
      await request(path, {
        method: 'POST',
        body: yaml,
        headers: { 'Content-Type': 'application/yaml' },
      })
    ).json() as Promise<T>,
  /** DELETE answers 204 with no body. */
  delete: async (path: string) => void (await request(path, { method: 'DELETE' })),
}
