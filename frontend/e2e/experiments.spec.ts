import { expect, test } from '@playwright/test'
import { login, RESEARCHER } from './helpers.ts'

const COMPLETED = 'Test dönemi · düz forum' // exp-test-c2
const DRAFT = 'Doğrulama · prompt ayarı' // exp-val-c1

test.describe('deneyler ve canlı borsa', () => {
  test.beforeEach(async ({ page }) => {
    await login(page, RESEARCHER)
  })

  test('deney listesi yüklenir ve duruma göre filtrelenir', async ({ page }) => {
    const main = page.getByRole('main')
    await expect(main.getByRole('heading', { level: 2, name: 'Tüm deneyler' })).toBeVisible()
    const names = main.getByRole('heading', { level: 3 })
    await expect(names).toHaveCount(5)
    await expect(main.getByRole('figure')).toBeVisible() // the featured experiment's chart

    await page.getByRole('tab', { name: /^Taslak/ }).click()
    await expect(names).toHaveText([DRAFT])
    await expect(page).toHaveURL(/status=draft/)
  })

  test('deney açılır; canlı borsa grafiği, lider tablosu ve ajan sayfası görünür', async ({
    page,
  }) => {
    await page.getByRole('main').getByRole('link', { name: COMPLETED, exact: true }).click()
    await expect(page).toHaveURL(/\/experiments\/exp-test-c2\/live$/)
    await expect(page.getByRole('heading', { level: 1, name: COMPLETED })).toBeVisible()

    const chart = page.getByRole('figure', { name: 'BTC/USDT günlük mum grafiği' })
    await expect(chart.locator('canvas').first()).toBeVisible()
    await expect(page.getByText(/gün 31\/\d+/)).toBeVisible()

    const leaderboard = page.getByRole('region', { name: 'Lider tablosu' })
    await expect(leaderboard.getByRole('listitem')).toHaveCount(8)
    await expect(leaderboard.getByRole('link', { name: /Sıra 1:/ })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Son işlemler' })).toBeVisible()

    // Another asset: the chart follows and the choice is kept in the URL.
    await page.getByRole('tab', { name: /^ETH/ }).click()
    await expect(page.getByRole('figure', { name: 'ETH/USDT günlük mum grafiği' })).toBeVisible()
    await expect(page).toHaveURL(/asset=ETH/)

    // The transport jumps to the last simulated day.
    await page.getByRole('button', { name: 'Sona git' }).click()
    await expect(page.getByText(/gün (\d+)\/\1$/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Oynat' })).toBeDisabled()

    await leaderboard.getByRole('link', { name: /LLM · Momentum/ }).click()
    await expect(page).toHaveURL(/\/experiments\/exp-test-c2\/agents\/llm-momentum$/)
    await expect(page.getByRole('heading', { name: 'Kararlar ve gerekçeleri' })).toBeVisible()
  })

  test('taslak deney başlatılınca tamamlanır ve açılabilir', async ({ page }) => {
    const row = page.getByRole('listitem').filter({ hasText: DRAFT })
    await expect(row.getByText('Taslak')).toBeVisible()
    await expect(row.getByRole('link', { name: DRAFT })).toHaveCount(0)

    await row.getByRole('button', { name: 'Başlat' }).click()
    await expect(row.getByText('Tamamlandı')).toBeVisible()
    await row.getByRole('link', { name: DRAFT }).click()
    await expect(page.getByRole('figure', { name: /günlük mum grafiği/ })).toBeVisible()
  })

  test('deney YAML olarak indirilir', async ({ page }) => {
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: `${COMPLETED} YAML olarak indir` }).click()
    expect((await download).suggestedFilename()).toBe('exp-test-c2.yaml')
  })
})
