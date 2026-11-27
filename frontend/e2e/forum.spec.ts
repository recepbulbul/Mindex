import { expect, test } from '@playwright/test'
import { countOf, gotoApp, login, RESEARCHER } from './helpers.ts'

test.describe('forum ve hafıza tarayıcı', () => {
  test.beforeEach(async ({ page }) => {
    await login(page, RESEARCHER)
    await gotoApp(page, '/experiments/exp-test-c3/forum')
  })

  test('forum mesajları görünür; gönderen, rejim ve arama listeyi daraltır', async ({ page }) => {
    const messages = page.getByRole('region', { name: 'Forum mesajları' }).getByRole('listitem')
    await expect(messages.first()).toBeVisible()
    const total = await countOf(page, 'mesaj')
    expect(total).toBeGreaterThan(1)
    await expect(page.getByRole('heading', { name: 'Güven matrisi' })).toBeVisible()

    // Sender
    await page.getByLabel('Gönderen').selectOption({ label: 'LLM · Momentum' })
    await expect.poll(() => countOf(page, 'mesaj')).toBeLessThan(total)
    const bySender = await countOf(page, 'mesaj')
    expect(bySender).toBeGreaterThan(0)
    await expect(messages.filter({ hasText: 'LLM · Momentum' })).toHaveCount(
      Math.min(bySender, 100),
    )
    await page.getByLabel('Gönderen').selectOption({ label: 'Tüm ajanlar' })

    // Regime
    await page.getByLabel('Mesaj rejimi').selectOption({ label: 'Ayı' })
    await expect.poll(() => countOf(page, 'mesaj')).toBeLessThan(total)
    await page.getByLabel('Mesaj rejimi').selectOption({ label: 'Tüm rejimler' })

    // Search: the one injected message of the MCP guest, shown as filtered out.
    await page.getByLabel('Mesajlarda ara').fill('sistem talimatı')
    await expect(page.getByText('1 mesaj', { exact: true })).toBeVisible()
    await expect(messages).toHaveCount(1)
    await expect(messages).toContainText('Prompt injection şüphesi')

    await page.getByLabel('Mesajlarda ara').fill('böyle bir mesaj yok')
    await expect(page.getByText('Eşleşen mesaj yok')).toBeVisible()
  })

  test('hafıza tarayıcı dersleri gösterir; ajan, rejim ve arama listeyi daraltır', async ({
    page,
  }) => {
    await page.getByRole('tab', { name: 'Hafıza tarayıcı' }).click()
    await expect(page).toHaveURL(/view=memory/)
    const lessons = page.getByRole('main').getByRole('listitem')
    await expect(lessons.first()).toBeVisible()
    const total = await countOf(page, 'ders')
    expect(total).toBeGreaterThan(1)

    await page.getByLabel('Ajan').selectOption({ label: 'LLM · Momentum' })
    await expect.poll(() => countOf(page, 'ders')).toBeLessThan(total)
    const byAgent = await countOf(page, 'ders')
    await expect(lessons.filter({ hasText: 'LLM · Momentum' })).toHaveCount(Math.min(byAgent, 60))
    await page.getByLabel('Ajan').selectOption({ label: 'Tüm LLM ajanları' })

    await page.getByLabel('Rejim').selectOption({ label: 'Boğa' })
    await expect.poll(() => countOf(page, 'ders')).toBeLessThan(total)
    await page.getByLabel('Rejim').selectOption({ label: 'Tüm rejimler' })

    await page.getByLabel('Derslerde ara').fill('kaybettirdi')
    await expect.poll(() => countOf(page, 'ders')).toBeLessThan(total)
    const lost = await countOf(page, 'ders')
    await expect(lessons.filter({ hasText: 'kaybettirdi' })).toHaveCount(Math.min(lost, 60))

    await page.getByLabel('Derslerde ara').fill('böyle bir ders yok')
    await expect(page.getByText('Eşleşen ders yok')).toBeVisible()
  })
})
