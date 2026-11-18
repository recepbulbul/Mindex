import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router'
import { createQueryClient, Providers } from './app/providers'
import { routes } from './app/routes'
import './index.css'

async function enableMocking() {
  // The MSW mock API runs only when asked for: `.env.development` turns it on for `npm run dev`,
  // the GitHub Pages build sets it too. With VITE_USE_MOCKS=false (`.env.development.local`)
  // the app talks to the real backend, which the dev server proxies at /api.
  if (import.meta.env.VITE_USE_MOCKS !== 'true') {
    // A worker left registered by an earlier mock session must not answer for the real API.
    const registrations = (await navigator.serviceWorker?.getRegistrations().catch(() => [])) ?? []
    await Promise.all(
      registrations
        .filter((r) => r.active?.scriptURL.endsWith('/mockServiceWorker.js'))
        .map((r) => r.unregister()),
    )
    return
  }
  const { startMockApi, reconnectMockApi } = await import('./mocks/browser')
  await startMockApi()
  const { setApiRecovery } = await import('./api/client')
  setApiRecovery(reconnectMockApi)
}

const router = createBrowserRouter(routes, {
  basename: import.meta.env.BASE_URL.replace(/\/$/, ''),
})
const queryClient = createQueryClient()

await enableMocking()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Providers client={queryClient}>
      <RouterProvider router={router} />
    </Providers>
  </StrictMode>,
)
