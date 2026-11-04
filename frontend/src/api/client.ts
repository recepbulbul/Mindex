import type { ApiErrorBody } from './types'

// Absolute so the same code works in the browser and in Node-based tests.
export const API_BASE =
  import.meta.env.VITE_API_BASE_URL ?? `${globalThis.location.origin}${import.meta.env.BASE_URL}api`

const TOKEN_KEY = 'mindex.token'

// Prototype keeps the JWT in sessionStorage; the real API (P4) moves it to an httpOnly cookie.
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
const answeredByApi = (res: Response) => /json|yaml/.test(res.headers.get('Content-Type') ?? '')

let recoverApi: (() => Promise<void>) | null = null
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
      await recoverApi()
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

export const api = {
  get: async <T>(path: string) => (await request(path)).json() as Promise<T>,
  text: async (path: string) => (await request(path)).text(),
  post: async <T>(path: string, body?: unknown) =>
    (
      await request(path, {
        method: 'POST',
        body: body === undefined ? undefined : JSON.stringify(body),
      })
    ).json() as Promise<T>,
}
