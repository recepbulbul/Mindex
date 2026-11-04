import { setupWorker } from 'msw/browser'
import { handlers } from './handlers'

export const worker = setupWorker(...handlers)

const RELOAD_FLAG = 'mindex.msw-reload'

/** Reloads once so the mock service worker controls the page; never loops. */
export function reloadForMockApi() {
  if (sessionStorage.getItem(RELOAD_FLAG)) return
  sessionStorage.setItem(RELOAD_FLAG, '1')
  location.reload()
}

export async function startMockApi() {
  await worker.start({
    serviceWorker: { url: `${import.meta.env.BASE_URL}mockServiceWorker.js` },
    onUnhandledFrame: 'bypass',
    quiet: import.meta.env.PROD,
  })
  // A hard reload (Shift+F5) loads the page without its service worker, so API calls would
  // reach the dev server and get index.html back. One normal reload restores interception.
  if (navigator.serviceWorker.controller) sessionStorage.removeItem(RELOAD_FLAG)
  else reloadForMockApi()
}
