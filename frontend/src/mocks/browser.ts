import { setupWorker } from 'msw/browser'
import { handlers } from './handlers'

export const worker = setupWorker(...handlers)

const RELOAD_FLAG = 'mindex.msw-reload'
const options = {
  serviceWorker: { url: `${import.meta.env.BASE_URL}mockServiceWorker.js` },
  onUnhandledFrame: 'bypass',
  quiet: import.meta.env.PROD,
} as const

/** Reloads once so the mock service worker controls the page; never loops. */
function reloadOnce() {
  if (sessionStorage.getItem(RELOAD_FLAG)) return
  sessionStorage.setItem(RELOAD_FLAG, '1')
  location.reload()
}

export async function startMockApi() {
  await worker.start(options)
  // A hard reload (Shift+F5) loads the page without its service worker, so API calls would
  // reach the dev server instead. One normal reload restores interception.
  if (navigator.serviceWorker.controller) sessionStorage.removeItem(RELOAD_FLAG)
  else reloadOnce()
}

/**
 * Browsers stop an idle service worker (e.g. while the tab is in the background) and MSW's
 * restarted worker no longer knows this tab, so requests pass through to the dev server.
 * Re-announcing the page re-enables mocking without a reload; an uncontrolled page reloads.
 */
export async function reconnectMockApi() {
  if (!navigator.serviceWorker.controller) return reloadOnce()
  worker.stop()
  await worker.start(options)
}
