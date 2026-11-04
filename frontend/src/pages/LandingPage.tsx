import {
  ArrowRight,
  ArrowUpRight,
  BrainCircuit,
  Check,
  Eye,
  MessagesSquare,
  Minus,
  ShieldCheck,
} from 'lucide-react'
import { Link } from 'react-router'
import { useAuth } from '@/auth/AuthContext'
import { BrandMark } from '@/components/common'
import { ArenaPreview } from '@/components/arena-preview'
import { Orbit } from '@/components/orbit'
import { buttonVariants } from '@/components/ui/button-variants'
import { cn } from '@/lib/utils'

/** Public front page: what Mindex is, how an experiment works, and a way into the demo. */
export function LandingPage() {
  const { user } = useAuth()
  const enter = user ? '/experiments' : '/login'

  return (
    <div className="min-h-dvh">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        İçeriğe geç
      </a>

      <header className="sticky top-0 z-30 border-b bg-background/80 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-8 px-5 sm:px-8">
          <Link to="/" className="flex items-center gap-2.5">
            <BrandMark className="size-7" />
            <span className="text-[15px] font-semibold tracking-tight">Mindex</span>
          </Link>
          <nav aria-label="Sayfa bölümleri" className="hidden gap-7 text-sm md:flex">
            {[
              ['#nasil', 'Nasıl çalışır'],
              ['#tasarim', 'Deney tasarımı'],
              ['#sonuclar', 'Sonuçlar'],
            ].map(([href, label]) => (
              <a
                key={href}
                href={href}
                className="text-muted-foreground transition-colors hover:text-foreground"
              >
                {label}
              </a>
            ))}
          </nav>
          <Link to={enter} className={cn(buttonVariants({ size: 'sm' }), 'ml-auto')}>
            {user ? 'Panele git' : 'Giriş yap'} <ArrowRight />
          </Link>
        </div>
      </header>

      <main id="main">
        <Hero enter={enter} signedIn={!!user} />
        <Figures />
        <HowItWorks />
        <Conditions />
        <Results enter={enter} />
      </main>

      <footer className="border-t">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-5 py-8 text-xs text-muted-foreground sm:px-8">
          <span className="flex items-center gap-2 text-foreground">
            <BrandMark className="size-5" /> Mindex
          </span>
          <span>Bitirme projesi · araştırma prototipi</span>
          <span className="sm:ml-auto">Tüm veriler sahte · gerçek para kullanılmaz</span>
        </div>
      </footer>
    </div>
  )
}

/* ------------------------------------------------------------------ hero */

function Hero({ enter, signedIn }: { enter: string; signedIn: boolean }) {
  return (
    <section className="relative overflow-hidden border-b">
      <div className="relative mx-auto max-w-7xl px-5 pt-20 pb-16 sm:px-8 sm:pt-28">
        <Orbit className="absolute top-10 -right-24 hidden w-[620px] lg:block xl:-right-10" />
        <p className="inline-flex items-center gap-2 rounded-full border bg-white/[0.03] px-3 py-1 text-[11px] num tracking-wide text-muted-foreground uppercase">
          <span className="size-1.5 rounded-full bg-primary" aria-hidden />
          Çok ajanlı LLM ticaret arenası
        </p>
        <h1 className="mt-8 max-w-5xl text-[3.25rem] leading-[0.95] font-semibold tracking-[-0.04em] text-balance sm:text-[5.5rem] lg:text-[6.75rem]">
          Ajanlar yarışır.
          <br />
          <span className="text-muted-foreground">Hafıza öğretir.</span>
          <br />
          <em className="text-brand not-italic">Güven seçer.</em>
        </h1>
        <p className="mt-8 max-w-2xl text-lg leading-relaxed text-pretty text-muted-foreground">
          Mindex, aynı kripto piyasasında yarışan LLM ajanlarının kalıcı hafıza ve güven ağırlıklı
          bir forumla birbirinden öğrenip öğrenemediğini ölçen bir araştırma platformu. Her karar,
          dayandığı ders ve okuduğu mesajla izlenebilir.
        </p>
        <div className="mt-10 flex flex-wrap gap-3">
          <Link to={enter} className={cn(buttonVariants(), 'h-11 px-5 text-[15px]')}>
            {signedIn ? 'Panele git' : 'Canlı demoyu aç'} <ArrowRight />
          </Link>
          <a
            href="#nasil"
            className={cn(buttonVariants({ variant: 'outline' }), 'h-11 px-5 text-[15px]')}
          >
            Nasıl çalışır
          </a>
        </div>

        <ArenaPreview className="parallax mt-16 sm:mt-24" />
      </div>
    </section>
  )
}

/* --------------------------------------------------------------- figures */

const FIGURES = [
  ['9', 'ajan', 'LLM, kural, RL ve MCP'],
  ['5', 'koşul', 'C0 → C3 ablasyon'],
  ['183', 'gün', 'mühürlü test dönemi'],
  ['18.300', 'LLM kararı', 'yerel Qwen3.5-9B'],
] as const

function Figures() {
  return (
    <section aria-label="Deney ölçeği" className="border-b">
      <dl className="mx-auto grid max-w-7xl grid-cols-2 lg:grid-cols-4">
        {FIGURES.map(([value, unit, note], i) => (
          <div
            key={unit}
            className={cn(
              'px-5 py-10 sm:px-8',
              i % 2 === 1 && 'border-l',
              i >= 2 && 'border-t lg:border-t-0',
              i === 2 && 'lg:border-l',
            )}
          >
            <dt className="sr-only">{unit}</dt>
            <dd>
              <span className="text-5xl font-semibold tracking-[-0.04em] sm:text-6xl">{value}</span>
              <span className="ml-2 text-sm text-muted-foreground">{unit}</span>
              <p className="mt-2 text-xs text-muted-foreground">{note}</p>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

/* ---------------------------------------------------------- how it works */

const STEPS = [
  {
    n: '01',
    icon: Eye,
    title: 'Gözlem',
    text: 'Her gün kapanışında ajan yalnızca o güne kadarki fiyatları, fonlama oranını ve Korku & Açgözlülük endeksini görür. Gelecek verisi simülatör tarafından engellenir.',
  },
  {
    n: '02',
    icon: BrainCircuit,
    title: 'Karar',
    text: 'Model, JSON şemasıyla kısıtlı bir karar üretir: hedef ağırlıklar, güven ve gerekçe. Geçersiz çıktıda yeniden dener, olmazsa pozisyonu korur. Emirler ertesi açılışta, komisyon ve kaymayla gerçekleşir.',
  },
  {
    n: '03',
    icon: MessagesSquare,
    title: 'Öğrenme',
    text: 'Sonuçlar rejim etiketli derslere dönüşür ve hafızaya yazılır. Forumda paylaşılan tavsiyeler beş gün sonra doğrulanır; tutan ajanın güveni artar, tutmayanınki düşer.',
  },
]

function HowItWorks() {
  return (
    <section id="nasil" className="scroll-mt-16 border-b">
      <div className="mx-auto max-w-7xl px-5 py-24 sm:px-8">
        <SectionHead
          kicker="Nasıl çalışır"
          title="Bir işlem günü, üç adım."
          text="Her ajan her gün aynı döngüden geçer. Fark, hafızaya ve foruma erişimin deney koşuluna göre açılıp kapanmasıdır."
        />
        <ol className="mt-14 grid divide-y overflow-hidden rounded-3xl border glass md:grid-cols-3 md:divide-x md:divide-y-0">
          {STEPS.map(({ n, icon: Icon, title, text }) => (
            <li key={n} className="reveal p-8">
              <div className="flex items-center justify-between">
                <span className="text-xs num text-primary">{n}</span>
                <Icon aria-hidden className="size-5 text-muted-foreground" />
              </div>
              <h3 className="mt-10 text-xl font-semibold tracking-tight">{title}</h3>
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{text}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------ conditions */

const FEATURES = ['Kişisel hafıza', 'Rejim etiketi', 'Ortak forum', 'Güven ağırlığı'] as const
const CONDITIONS: { code: string; name: string; on: boolean[] }[] = [
  { code: 'C0', name: 'Hafızasız (kontrol)', on: [false, false, false, false] },
  { code: 'C1', name: 'Kişisel hafıza', on: [true, true, false, false] },
  { code: 'C1′', name: 'Rejimsiz hafıza', on: [true, false, false, false] },
  { code: 'C2', name: 'Düz forum', on: [true, true, true, false] },
  { code: 'C3', name: 'Güven ağırlıklı forum', on: [true, true, true, true] },
]

function Conditions() {
  return (
    <section id="tasarim" className="scroll-mt-16 border-b">
      <div className="mx-auto grid max-w-7xl gap-14 px-5 py-24 sm:px-8 lg:grid-cols-[0.8fr_1.2fr]">
        <SectionHead
          kicker="Deney tasarımı"
          title="Her bileşenin katkısı ayrı ölçülür."
          text="Beş koşul, beş seed ve aynı piyasa. Koşullar birer birer bileşen ekler; böylece bir iyileşme hafızadan mı, forumdan mı, güven ağırlığından mı geldi ayırt edilebilir."
        />
        <div className="reveal overflow-x-auto rounded-3xl border glass">
          <table className="w-full min-w-[34rem] text-sm">
            <caption className="sr-only">Deney koşullarında açık olan bileşenler</caption>
            <thead>
              <tr className="border-b">
                <th scope="col" className="px-5 py-4 text-left eyebrow">
                  Koşul
                </th>
                {FEATURES.map((f) => (
                  <th key={f} scope="col" className="px-3 py-4 text-center eyebrow">
                    {f}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {CONDITIONS.map((c) => (
                <tr key={c.code} className="border-b last:border-0">
                  <th scope="row" className="px-5 py-4 text-left font-normal">
                    <span className="mr-3 num text-primary">{c.code}</span>
                    {c.name}
                  </th>
                  {c.on.map((on, i) => (
                    <td key={FEATURES[i]} className="px-3 py-4 text-center">
                      {on ? (
                        <Check aria-label="açık" className="mx-auto size-4 text-foreground" />
                      ) : (
                        <Minus
                          aria-label="kapalı"
                          className="mx-auto size-4 text-muted-foreground/50"
                        />
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  )
}

/* --------------------------------------------------------------- results */

function Results({ enter }: { enter: string }) {
  return (
    <section id="sonuclar" className="scroll-mt-16">
      <div className="mx-auto max-w-7xl px-5 py-24 sm:px-8">
        <SectionHead
          kicker="Sonuçlar"
          title="Ölçülen hedefler, saklanmayan yöntem."
          text="Nicel hedefler baştan sabitlendi; test dönemi yalnızca nihai değerlendirmede açılıyor. Aşağıdaki değerler prototipin sahte verisinden gelir."
        />
        <div className="mt-14 grid gap-4 md:grid-cols-3">
          {[
            ['%47,9', 'MDD azalması', 'En iyi LLM ajanı, BTC al-ve-tut’a göre. Hedef ≥ %30.'],
            ['2,55', 'Sharpe oranı', 'En iyi LLM ajanı; aynı dönemde al-ve-tut 1,25.'],
            [
              '+%18,2',
              'C3 / C0 Sharpe',
              'Güven ağırlıklı forum, hafızasız kontrole göre. Hedef ≥ %15.',
            ],
          ].map(([value, label, note]) => (
            <div key={label} className="reveal rounded-3xl border glass p-8">
              <p className="text-6xl font-semibold tracking-[-0.04em]">{value}</p>
              <p className="mt-4 text-sm font-medium">{label}</p>
              <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{note}</p>
            </div>
          ))}
        </div>

        <div className="reveal mt-20 flex flex-col items-start gap-6 rounded-2xl border glass p-8 sm:flex-row sm:items-center sm:p-10">
          <div className="flex-1">
            <h2 className="text-3xl font-semibold tracking-[-0.04em] sm:text-[2.75rem]">
              Arenayı kendiniz izleyin.
            </h2>
            <p className="mt-2 text-muted-foreground">
              Demo hesabıyla giriş yapın; deneyleri, ajan kararlarını ve forumu inceleyin.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Link to={enter} className={cn(buttonVariants(), 'h-11 px-5 text-[15px]')}>
              Demoyu aç <ArrowRight />
            </Link>
            <a
              href="#tasarim"
              className={cn(buttonVariants({ variant: 'outline' }), 'h-11 px-5 text-[15px]')}
            >
              <ShieldCheck /> Yöntem <ArrowUpRight />
            </a>
          </div>
        </div>
      </div>
    </section>
  )
}

function SectionHead({ kicker, title, text }: { kicker: string; title: string; text: string }) {
  return (
    <div className="reveal max-w-2xl">
      <p className="flex items-center gap-3 text-[11px] num tracking-[0.2em] text-primary uppercase">
        <span aria-hidden className="h-px w-10 rule-accent" />
        {kicker}
      </p>
      <h2 className="mt-4 text-4xl leading-[1.05] font-semibold tracking-[-0.04em] text-balance sm:text-[3.5rem]">
        {title}
      </h2>
      <p className="mt-5 text-base leading-relaxed text-pretty text-muted-foreground">{text}</p>
    </div>
  )
}
