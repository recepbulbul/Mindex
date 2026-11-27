import { expect, test } from '@playwright/test'
import { DEMO_PASSWORD, fillLogin, gotoApp, login, RESEARCHER } from './helpers.ts'

test.describe('oturum', () => {
  test('oturum yokken korumalı sayfa girişe yönlendirir', async ({ page }) => {
    await gotoApp(page, '/experiments')
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByRole('heading', { name: 'Mindex Arena' })).toBeVisible()
  })

  test('yanlış parola hata gösterir ve girişte kalır', async ({ page }) => {
    await gotoApp(page, '/login')
    await fillLogin(page, RESEARCHER, 'yanlis-parola')
    await expect(page.getByRole('alert')).toHaveText('E-posta veya parola hatalı.')
    await expect(page).toHaveURL(/\/login$/)
  })

  test('araştırmacı giriş yapar ve deneyleri görür', async ({ page }) => {
    await login(page, RESEARCHER)
    await expect(page).toHaveURL(/\/experiments$/)
    const menu = page.getByRole('navigation', { name: 'Ana menü' })
    await expect(menu.getByRole('link', { name: 'Yeni deney' })).toBeVisible()
    await expect(page.getByRole('link', { name: `${RESEARCHER} Araştırmacı` })).toBeVisible()
  })

  test('giriş, istenen korumalı sayfaya geri döndürür', async ({ page }) => {
    await gotoApp(page, '/studies')
    await expect(page).toHaveURL(/\/login$/)
    await fillLogin(page, RESEARCHER, DEMO_PASSWORD)
    await expect(page).toHaveURL(/\/studies$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Çalışmalar' })).toBeVisible()
  })

  test('çıkış yapınca oturum kapanır', async ({ page }) => {
    await login(page, RESEARCHER)
    await page.getByRole('button', { name: 'Çıkış yap' }).click()
    await expect(page).toHaveURL(/\/login$/)

    await gotoApp(page, '/experiments')
    await expect(page).toHaveURL(/\/login$/)
  })
})
