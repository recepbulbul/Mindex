import { expect, type Page } from '@playwright/test'

// The mock API's demo accounts (src/mocks/fixtures.ts); they exist only in MSW.
export const RESEARCHER = 'arastirmaci@mindex.dev'
export const VIEWER = 'izleyici@mindex.dev'
export const DEMO_PASSWORD = 'mindex-demo'

/**
 * Opens a path and waits until the MSW service worker controls the page. On its first load
 * the app may reload once to get there (src/mocks/browser.ts); acting before that reload
 * would lose the input. A full load also resets the mock data to its seed.
 */
export async function gotoApp(page: Page, path: string) {
  await page.goto(path)
  await page.waitForFunction(
    "navigator.serviceWorker.controller !== null && sessionStorage.getItem('mindex.msw-reload') === null",
  )
}

export async function fillLogin(page: Page, email: string, password: string) {
  await page.getByLabel('E-posta').fill(email)
  await page.getByLabel('Parola').fill(password)
  await page.getByRole('button', { name: 'Giriş yap' }).click()
}

export async function login(page: Page, email: string) {
  await gotoApp(page, '/login')
  await fillLogin(page, email, DEMO_PASSWORD)
  await expect(page.getByRole('heading', { level: 1, name: 'Deneyler' })).toBeVisible()
}

/** "42 mesaj" / "17 ders" → 42 / 17. */
export async function countOf(page: Page, unit: 'mesaj' | 'ders') {
  const text = await page.getByText(new RegExp(`^\\d+ ${unit}`)).innerText()
  return Number.parseInt(text, 10)
}
