import { expect, test } from '@playwright/test'
import { gotoApp, login, RESEARCHER, VIEWER } from './helpers.ts'

test.describe('rol denetimi', () => {
  test('izleyici yeni deney sayfasına ulaşamaz ve deney başlatamaz', async ({ page }) => {
    await login(page, VIEWER)
    await expect(page.getByRole('link', { name: `${VIEWER} İzleyici` })).toBeVisible()
    await expect(page.getByRole('heading', { level: 3 })).toHaveCount(5)
    await expect(page.getByRole('link', { name: 'Yeni deney' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Başlat' })).toHaveCount(0)

    await gotoApp(page, '/experiments/new')
    await expect(page).toHaveURL(/\/experiments$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Deneyler' })).toBeVisible()
  })

  test('araştırmacı yeni deney sayfasını açar', async ({ page }) => {
    await login(page, RESEARCHER)
    await page.getByRole('main').getByRole('link', { name: 'Yeni deney' }).click()
    await expect(page).toHaveURL(/\/experiments\/new$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Yeni deney' })).toBeVisible()
    await expect(page.getByLabel('Deney adı')).toBeVisible()
  })
})
