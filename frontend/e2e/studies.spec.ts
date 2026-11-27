import { expect, test } from '@playwright/test'
import { login, RESEARCHER, VIEWER } from './helpers.ts'

const STUDY = 'C0–C3 karşılaştırması' // the form's default name

test.describe('çalışmalar', () => {
  // The mock API starts without studies, so the journey creates one. Navigation stays inside
  // the app: a full page load would reset the mock data.
  test('araştırmacı smoke çalışması oluşturur, başlatır ve koşulları karşılaştırır', async ({
    page,
  }) => {
    await login(page, RESEARCHER)
    const menu = page.getByRole('navigation', { name: 'Ana menü' })
    await menu.getByRole('link', { name: 'Çalışmalar' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Çalışmalar' })).toBeVisible()
    await expect(page.getByText('Henüz çalışma yok')).toBeVisible()

    await expect(page.getByLabel('Ad', { exact: true })).toHaveValue(STUDY)
    await page.getByRole('button', { name: '5 deney oluştur' }).click()

    // Study page: one draft run per condition, no comparison yet.
    await expect(page).toHaveURL(/\/studies\/study-/)
    await expect(page.getByRole('heading', { level: 1, name: STUDY })).toBeVisible()
    const runs = page
      .getByRole('table')
      .filter({ has: page.getByRole('columnheader', { name: 'Seed' }) })
    await expect(runs.getByRole('link', { name: /: draft$/ })).toHaveCount(5)
    await expect(
      page.getByText('Karşılaştırma, ilk koşu tamamlanınca burada görünür.'),
    ).toBeVisible()

    await page.getByRole('button', { name: 'Başlat' }).click()
    await expect(runs.getByRole('link', { name: /: completed$/ })).toHaveCount(5)

    await expect(
      page.getByRole('heading', { name: 'Koşul karşılaştırması (5 koşul, 5 koşu)' }),
    ).toBeVisible()
    const comparison = page
      .getByRole('table')
      .filter({ has: page.getByRole('columnheader', { name: 'vs C0' }) })
    await expect(comparison.getByRole('row')).toHaveCount(6) // header + C0, C1, C1′, C2, C3
    await expect(comparison.getByRole('row', { name: /C1′ · Rejimsiz hafıza/ })).toBeVisible()

    await expect(page.getByRole('heading', { name: 'Koşul farkları' })).toBeVisible()
    const differences = page
      .getByRole('table')
      .filter({ has: page.getByRole('columnheader', { name: 'ΔSharpe' }) })
    await expect(differences.getByRole('row')).toHaveCount(6) // header + 5 pairs
    await expect(differences.getByRole('row', { name: /C3 − C0 hepsi birlikte/ })).toBeVisible()

    // Back on the list the study is there, complete, and opens again.
    await page.getByRole('main').getByRole('link', { name: 'Çalışmalar' }).click()
    const item = page.getByRole('list', { name: 'Çalışmalar' }).getByRole('link', { name: STUDY })
    await expect(item).toContainText('5/5 koşu tamamlandı')
    await item.click()
    await expect(page.getByRole('heading', { name: 'Koşul farkları' })).toBeVisible()
  })

  test('izleyici çalışma oluşturamaz', async ({ page }) => {
    await login(page, VIEWER)
    await page
      .getByRole('navigation', { name: 'Ana menü' })
      .getByRole('link', { name: 'Çalışmalar' })
      .click()
    await expect(page.getByText('Henüz çalışma yok')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Yeni çalışma' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: /deney oluştur/ })).toHaveCount(0)
  })
})
