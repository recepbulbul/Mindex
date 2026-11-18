import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { tokenStore } from '@/api/client'
import type { UserRole } from '@/api/types'
import { createQueryClient, Providers } from '@/app/providers'
import { routes } from '@/app/routes'

export function signIn(role: UserRole) {
  const email = role === 'researcher' ? 'arastirmaci@mindex.dev' : 'izleyici@mindex.dev'
  // The mock's token format, so it knows who owns what (as after a real login).
  tokenStore.set(`mock.${role}.${btoa(email)}.${crypto.randomUUID()}`)
  sessionStorage.setItem('mindex.user', JSON.stringify({ email, role }))
}

export function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const client = createQueryClient()
  client.setDefaultOptions({ queries: { retry: false } })
  const user = userEvent.setup()
  const utils = render(
    <Providers client={client}>
      <RouterProvider router={router} />
    </Providers>,
  )
  return { ...utils, router, user }
}
