import { readFile } from 'node:fs/promises'
import { expect, test } from '@playwright/test'
import { login, RESEARCHER } from './helpers.ts'

test.describe('rapor', () => {
  test.beforeEach(async ({ page }) => {
    await login(page, RESEARCHER)
    await page
      .getByRole('listitem')
      .filter({ hasText: 'Test dönemi · düz forum' })
      .getByRole('link', { name: 'Rapor' })
      .click()
    await expect(page).toHaveURL(/\/experiments\/exp-test-c2\/report$/)
  })

  test('ajan metrikleri, portföy grafiği ve koşul karşılaştırması görünür', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Ajan metrikleri' })).toBeVisible()
    const metrics = page
      .getByRole('table')
      .filter({ has: page.getByRole('columnheader', { name: 'İşlem' }) })
    await expect(metrics.getByRole('columnheader')).toHaveText([
      'Ajan',
      'Getiri',
      'Sharpe',
      'MDD',
      'İşlem',
    ])
    await expect(metrics.getByRole('row')).toHaveCount(9) // header + 8 agents
    await expect(metrics.getByRole('row', { name: /Al-ve-tut BTC/ })).toBeVisible()
    await expect(metrics.getByRole('row', { name: /PPO/ })).toBeVisible()
    await expect(metrics.getByText('en iyi')).toHaveCount(1)

    await expect(page.getByText('MDD azalması (hedef ≥ %30)')).toBeVisible()
    await expect(
      page.getByRole('figure', { name: 'Ajanların portföy değeri zaman serisi' }),
    ).toBeVisible()

    await expect(page.getByRole('heading', { name: /^Koşul karşılaştırması/ })).toBeVisible()
    const comparison = page
      .getByRole('table')
      .filter({ has: page.getByRole('columnheader', { name: 'vs C0' }) })
    await expect(comparison.getByRole('row', { name: /C0 · Hafızasız/ })).toBeVisible()
    await expect(comparison.getByRole('row', { name: /C3 · Güven ağırlıklı forum/ })).toBeVisible()
    await expect(comparison.getByRole('img', { name: /^Sharpe / }).first()).toBeVisible()
  })

  test('CSV dışa aktarımı ajan metriklerini indirir', async ({ page }) => {
    const pending = page.waitForEvent('download')
    await page.getByRole('button', { name: 'CSV' }).click()
    const download = await pending
    expect(download.suggestedFilename()).toBe('mindex-exp-test-c2-report.csv')

    const lines = (await readFile(await download.path(), 'utf8')).split('\n')
    expect(lines[0]).toBe('"agent","total_return","sharpe","max_drawdown","trades"')
    expect(lines).toHaveLength(9) // header + 8 agents
    expect(lines.some((l) => l.startsWith('"LLM · Momentum",'))).toBe(true)
  })
})
