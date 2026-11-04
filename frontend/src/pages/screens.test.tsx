import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderApp, signIn } from '@/test/render'

describe('landing page', () => {
  it('introduces the arena and links anonymous visitors to the demo login', async () => {
    const { user, router } = renderApp('/')
    expect(
      await screen.findByRole('heading', { level: 1, name: /Ajanlar yarışır/ }),
    ).toBeInTheDocument()
    expect(screen.getByRole('table', { name: /Deney koşullarında/ })).toBeInTheDocument()
    await user.click(screen.getByRole('link', { name: /Canlı demoyu aç/ }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'))
  })
})

describe('login (F1)', () => {
  it('redirects anonymous users to login', async () => {
    const { router } = renderApp('/experiments')
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'))
  })

  it('shows field validation before calling the API', async () => {
    const { user } = renderApp('/login')
    await user.click(screen.getByRole('button', { name: 'Giriş yap' }))
    expect(await screen.findByText('Geçerli bir e-posta girin')).toBeInTheDocument()
  })

  it('rejects wrong credentials', async () => {
    const { user } = renderApp('/login')
    await user.type(screen.getByLabelText('E-posta'), 'arastirmaci@mindex.dev')
    await user.type(screen.getByLabelText('Parola'), 'yanlis-parola')
    await user.click(screen.getByRole('button', { name: 'Giriş yap' }))
    expect(await screen.findByText('E-posta veya parola hatalı.')).toBeInTheDocument()
  })

  it('logs in with a demo account and lands on experiments', async () => {
    const { user, router } = renderApp('/login')
    await user.click(screen.getByRole('button', { name: /Araştırmacı · arastirmaci/ }))
    await user.click(screen.getByRole('button', { name: 'Giriş yap' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/experiments'))
    // The name appears in the featured hero and in its card.
    expect(await screen.findAllByText('Test dönemi · güven ağırlıklı forum')).not.toHaveLength(0)
  })
})

describe('account', () => {
  it('opens the account page from the menu', async () => {
    signIn('researcher')
    const { user, router } = renderApp('/experiments')
    await user.click(
      (await screen.findAllByRole('link', { name: /Hesap|arastirmaci@mindex\.dev/ }))[0]!,
    )
    await waitFor(() => expect(router.state.location.pathname).toBe('/account'))
    expect(await screen.findByRole('button', { name: /Oturumu kapat/ })).toBeInTheDocument()
  })

  it('signs out from the menu on any screen', async () => {
    signIn('viewer')
    const { user, router } = renderApp('/experiments')
    await user.click((await screen.findAllByRole('button', { name: 'Çıkış yap' }))[0]!)
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'))
  })
})

describe('roles', () => {
  it('viewer cannot open the new experiment form', async () => {
    signIn('viewer')
    const { router } = renderApp('/experiments/new')
    await waitFor(() => expect(router.state.location.pathname).toBe('/experiments'))
    expect(screen.queryByRole('link', { name: /Yeni deney/ })).not.toBeInTheDocument()
  })
})

describe('experiment setup (F2)', () => {
  it('validates and creates a draft experiment', async () => {
    signIn('researcher')
    const { user, router } = renderApp('/experiments/new')
    const submit = await screen.findByRole('button', { name: 'Deneyi oluştur' })

    await user.click(submit)
    expect(await screen.findByText('En az 3 karakter')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Deney adı'), 'Yeni doğrulama deneyi')
    await user.click(submit)

    await waitFor(() => expect(router.state.location.pathname).toBe('/experiments'))
    const row = (await screen.findByText('Yeni doğrulama deneyi')).closest('li')!
    expect(within(row).getByText('Taslak')).toBeInTheDocument()
  })

  it('warns when the period touches the sealed test window', async () => {
    signIn('researcher')
    const { user } = renderApp('/experiments/new')
    const end = await screen.findByLabelText('Bitiş')
    await user.clear(end)
    await user.type(end, '2026-05-01')
    expect(await screen.findByText(/test penceresiyle/)).toBeInTheDocument()
  })
})

describe('live screen (F5)', () => {
  it('shows chart, leaderboard and replay controls', async () => {
    signIn('viewer')
    const { user } = renderApp('/experiments/exp-test-c3/live')
    expect(await screen.findByRole('figure', { name: /BTC\/USDT/ })).toBeInTheDocument()
    expect(screen.getByText('Lider tablosu')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /LLM · Momentum/ })).toBeInTheDocument()

    const slider = screen.getByLabelText('Simülasyon günü')
    expect(slider).toHaveValue('30')
    await user.click(screen.getByRole('button', { name: 'Sona git' }))
    expect(slider).toHaveValue('182')
  })

  it('keeps the chosen asset in the URL and ignores unknown ones', async () => {
    signIn('viewer')
    const { user, router } = renderApp('/experiments/exp-test-c3/live?asset=ETH')
    expect(await screen.findByRole('figure', { name: /ETH\/USDT/ })).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: /SOL/ }))
    expect(router.state.location.search).toBe('?asset=SOL')

    await router.navigate('/experiments/exp-test-c3/live?asset=DOGE')
    expect(await screen.findByRole('figure', { name: /BTC\/USDT/ })).toBeInTheDocument()
  })

  it('plays from the day on screen and stops at the last day', async () => {
    signIn('viewer')
    const { user } = renderApp('/experiments/exp-test-c3/live')
    const slider = await screen.findByLabelText('Simülasyon günü')
    // Play at max speed from two days before the end.
    await user.click(screen.getByRole('radio', { name: /20/ }))
    fireEvent.change(slider, { target: { value: '180' } })
    await user.click(screen.getByRole('button', { name: 'Oynat' }))
    await waitFor(() => expect(slider).toHaveValue('182'))
    expect(screen.getByRole('button', { name: 'Oynat' })).toBeDisabled()
  })

  it('explains that a draft has not started', async () => {
    signIn('viewer')
    renderApp('/experiments/exp-val-c1/live')
    expect(await screen.findByText('Bu deney henüz başlatılmadı.')).toBeInTheDocument()
  })
})

describe('agent detail (F6)', () => {
  it('lists decisions with rationale and trust scores', async () => {
    signIn('viewer')
    renderApp('/experiments/exp-test-c3/agents/llm-momentum')
    expect(await screen.findByRole('heading', { name: 'LLM · Momentum' })).toBeInTheDocument()
    expect(await screen.findByText('Kararlar ve gerekçeleri')).toBeInTheDocument()
    expect(screen.getByText(/183 karar/)).toBeInTheDocument()
    expect(screen.getByText('Güven skorları')).toBeInTheDocument()
  })
})

describe('forum and memory (F7)', () => {
  it('marks prompt-injection messages as filtered', async () => {
    signIn('viewer')
    const { user } = renderApp('/experiments/exp-test-c3/forum')
    await user.click(await screen.findByLabelText('Yalnızca filtrelenenler'))
    expect(await screen.findByText(/ajanlara iletilmedi/)).toBeInTheDocument()
  })

  it('opens the memory browser from the URL', async () => {
    signIn('viewer')
    renderApp('/experiments/exp-test-c3/forum?view=memory')
    expect(await screen.findByRole('tab', { name: 'Hafıza tarayıcı' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })

  it('filters lessons by regime', async () => {
    signIn('viewer')
    const { user } = renderApp('/experiments/exp-test-c3/forum')
    await user.click(await screen.findByRole('tab', { name: 'Hafıza tarayıcı' }))
    await screen.findByText(/\d+ ders/)
    await user.selectOptions(screen.getByLabelText('Rejim'), 'bear')
    await waitFor(() => {
      const badges = screen.getAllByText(/^(Boğa|Ayı|Yatay)$/).filter((el) => el.tagName === 'SPAN')
      expect(badges.length).toBeGreaterThan(0)
      expect(badges.every((b) => b.textContent === 'Ayı')).toBe(true)
    })
  })
})

describe('report (F8)', () => {
  it('shows agent metrics and the condition comparison', async () => {
    signIn('viewer')
    renderApp('/experiments/exp-test-c3/report')
    expect(await screen.findByText('Ajan metrikleri')).toBeInTheDocument()
    expect(screen.getByText(/Koşul karşılaştırması/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /CSV/ })).toBeInTheDocument()
  })
})
