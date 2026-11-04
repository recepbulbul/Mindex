import {
  Clock,
  Pause,
  Play,
  RotateCcw,
  SkipForward,
  TrendingDown,
  TrendingUp,
  Trophy,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import { useExperiment, useTimeline } from '@/api/queries'
import type { Asset } from '@/api/types'
import { CandleChart, type TradeMarker } from '@/components/charts/charts'
import { RegimeBadge } from '@/components/common'
import { AgentAvatar, AssetOrb } from '@/components/identity'
import { Button } from '@/components/ui/button'
import { segmentClass, segmentedClass } from '@/components/ui/button-variants'
import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Select,
  Skeleton,
} from '@/components/ui/primitives'
import { rovingKeyDown } from '@/lib/roving'
import { useSearchParam } from '@/lib/search-param'
import {
  cn,
  formatDate,
  formatNum,
  formatPct,
  formatPrice,
  formatShortDate,
  formatUsd,
} from '@/lib/utils'

const SPEEDS = [1, 5, 20] as const
const BASE_TICK_MS = 600
const ROW = 46 // leaderboard row height in px; rows slide by this much when ranks change

export default function LivePage() {
  const { id = '' } = useParams()
  const experiment = useExperiment(id)
  const isDraft = experiment.data?.status === 'draft'
  const timeline = useTimeline(id, experiment.isSuccess && !isDraft)

  // Only the experiment's own assets are valid; the first one is the default.
  const assets = experiment.data?.assets ?? []
  const [asset, setAsset] = useSearchParam<Asset>('asset', assets, assets[0] ?? 'BTC')
  const [agentFilter, setAgentFilter] = useState('llm-momentum')
  const [cursor, setCursor] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(5)

  const lastIndex = (timeline.data?.days.length ?? 1) - 1
  // Live experiments open at the latest tick; replays open at day 30 so there is history to see.
  const at = cursor ?? (experiment.data?.mode === 'live' ? lastIndex : Math.min(30, lastIndex))

  // Playback stops by itself at the last day; the interval lives as long as playback does,
  // not one tick (it used to be recreated on every step because it depended on `at`).
  const isPlaying = playing && at < lastIndex
  useEffect(() => {
    if (!isPlaying) return
    const timer = setInterval(
      () => setCursor((c) => Math.min((c ?? 0) + 1, lastIndex)),
      BASE_TICK_MS / speed,
    )
    return () => clearInterval(timer)
  }, [isPlaying, speed, lastIndex])

  const view = useMemo(() => {
    const t = timeline.data
    if (!t) return null
    const day = t.days[at]!
    const candles = t.candles[asset].slice(0, at + 1)
    const visibleTrades = t.trades.filter((x) => x.day <= day)
    const markers: TradeMarker[] = visibleTrades
      .filter((x) => x.asset === asset && (agentFilter === 'all' || x.agentId === agentFilter))
      .map((x) => ({
        time: x.day,
        side: x.side,
        label: agentFilter === 'all' ? x.agentId.replace('llm-', '') : '',
      }))
    const runs = t.runs.map((r) => {
      const eq = r.equity[at]!.equity
      return { agent: r.agent, equity: eq, ret: eq / r.equity[0]!.equity - 1 }
    })
    const ranked = [...runs].sort((a, b) => b.equity - a.equity)
    const tickers = (Object.keys(t.candles) as Asset[]).map((a) => {
      const last = t.candles[a][at]!.close
      const prev = t.candles[a][at - 1]?.close ?? last
      return { asset: a, price: last, change: last / prev - 1 }
    })
    return {
      day,
      regime: t.regimes[at]!,
      candles,
      markers,
      runs,
      rank: new Map(ranked.map((r, i) => [r.agent.id, i])),
      leader: ranked[0]!,
      tickers,
      feed: visibleTrades.slice(-10).reverse(),
      price: candles.at(-1)!.close,
      change: candles.at(-1)!.close / (candles.at(-2)?.close ?? candles.at(-1)!.close) - 1,
    }
  }, [timeline.data, at, asset, agentFilter])

  if (experiment.error) return <ErrorState error={experiment.error} />
  if (isDraft)
    return (
      <Card>
        <EmptyState icon={<Clock />} title="Bu deney henüz başlatılmadı.">
          <Link to="/experiments" className="text-primary underline-offset-4 hover:underline">
            Deneylere dön
          </Link>
        </EmptyState>
      </Card>
    )
  if (timeline.error)
    return <ErrorState error={timeline.error} onRetry={() => void timeline.refetch()} />
  if (!view || !experiment.data) return <Skeleton className="h-[480px]" />

  const exp = experiment.data
  const equities = view.runs.map((r) => r.equity)
  const lo = Math.min(...equities)
  const span = Math.max(...equities) - lo || 1
  const nameOf = (aid: string) => view.runs.find((r) => r.agent.id === aid)?.agent.name ?? aid
  const progress = lastIndex > 0 ? (at / lastIndex) * 100 : 100

  return (
    <>
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_340px] xl:gap-x-8">
        {/* Below xl the wrapper dissolves so the order is chart, leaderboard, trades. */}
        <div className="contents xl:grid xl:min-w-0 xl:gap-4">
          <section className="stage order-1 min-w-0 xl:order-none">
            {/* Asset switcher: compact, so the chart starts high on the first screen. */}
            <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2">
              <div
                role="tablist"
                aria-label="Varlık"
                onKeyDown={rovingKeyDown}
                tabIndex={-1}
                className="flex flex-wrap gap-1"
              >
                {view.tickers
                  .filter((tk) => exp.assets.includes(tk.asset))
                  .map((tk) => {
                    const active = tk.asset === asset
                    return (
                      <button
                        key={tk.asset}
                        type="button"
                        role="tab"
                        aria-selected={active}
                        tabIndex={active ? 0 : -1}
                        onClick={() => setAsset(tk.asset)}
                        className={cn(
                          'flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs transition-colors',
                          active
                            ? 'bg-white/[0.08] text-foreground shadow-[inset_0_1px_0_rgb(255_255_255/0.08)]'
                            : 'text-muted-foreground hover:bg-white/[0.04] hover:text-foreground',
                        )}
                      >
                        <AssetOrb asset={tk.asset} className="size-4 text-[8px] ring-0" />
                        {tk.asset}
                        <span className={cn('num', tk.change >= 0 ? 'text-up' : 'text-down')}>
                          {formatPct(tk.change)}
                        </span>
                      </button>
                    )
                  })}
              </div>
            </div>
            <div className="flex flex-wrap items-end gap-x-5 gap-y-2">
              <div className="flex items-center gap-3">
                <div>
                  <p className="text-xs text-muted-foreground">{asset}/USDT · günlük</p>
                  <div className="flex items-baseline gap-2.5">
                    <span className="text-silver text-4xl leading-tight font-medium num tracking-tight">
                      {formatPrice(view.price)}
                    </span>
                    <span
                      className={cn(
                        'inline-flex items-center gap-1 text-sm num',
                        view.change >= 0 ? 'text-up' : 'text-down',
                      )}
                    >
                      {view.change >= 0 ? (
                        <TrendingUp className="size-3.5" />
                      ) : (
                        <TrendingDown className="size-3.5" />
                      )}
                      {formatPct(view.change)}
                    </span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                Rejim <RegimeBadge regime={view.regime} />
              </div>
              <label className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
                İşlemleri göster
                <Select
                  value={agentFilter}
                  onChange={(e) => setAgentFilter(e.target.value)}
                  className="h-8 w-48 text-xs"
                >
                  <option value="all">Tüm ajanlar</option>
                  {view.runs.map((r) => (
                    <option key={r.agent.id} value={r.agent.id}>
                      {r.agent.name}
                    </option>
                  ))}
                </Select>
              </label>
            </div>

            <div className="-mx-1 pt-2">
              <CandleChart
                candles={view.candles}
                markers={view.markers}
                height="clamp(360px, calc(100dvh - 340px), 640px)"
                label={`${asset}/USDT günlük mum grafiği`}
              />
            </div>

            {/* Transport: play/pause, speed, scrubber with a gradient progress fill. */}
            <div className="mt-3 flex flex-wrap items-center gap-3 rounded-2xl px-4 py-3 band">
              <div className="flex items-center gap-1">
                <Button
                  size="icon"
                  aria-label={isPlaying ? 'Duraklat' : 'Oynat'}
                  onClick={() => {
                    // Playback continues from the day on screen.
                    setCursor(at)
                    setPlaying(!isPlaying)
                  }}
                  disabled={at >= lastIndex}
                  className="size-10 rounded-full"
                >
                  {isPlaying ? <Pause /> : <Play />}
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label="Başa sar"
                  onClick={() => {
                    setPlaying(false)
                    setCursor(0)
                  }}
                >
                  <RotateCcw />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label="Sona git"
                  onClick={() => {
                    setPlaying(false)
                    setCursor(lastIndex)
                  }}
                >
                  <SkipForward />
                </Button>
              </div>
              <div
                role="radiogroup"
                aria-label="Oynatma hızı"
                className={segmentedClass}
                onKeyDown={rovingKeyDown}
                tabIndex={-1}
              >
                {SPEEDS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    role="radio"
                    aria-checked={s === speed}
                    tabIndex={s === speed ? 0 : -1}
                    onClick={() => setSpeed(s)}
                    className={cn(segmentClass(s === speed), 'num')}
                  >
                    {s}×
                  </button>
                ))}
              </div>
              <div className="relative flex min-w-40 flex-1 items-center">
                <span
                  aria-hidden
                  className="pointer-events-none absolute inset-x-0 h-1.5 rounded-full bg-white/[0.08]"
                />
                <span
                  aria-hidden
                  className="pointer-events-none absolute left-0 h-1.5 rounded-full bg-brand"
                  style={{ width: `${progress}%` }}
                />
                <input
                  type="range"
                  min={0}
                  max={lastIndex}
                  value={at}
                  onChange={(e) => setCursor(Number(e.target.value))}
                  aria-label="Simülasyon günü"
                  className="scrubber relative w-full"
                />
              </div>
              <span className="text-xs num text-muted-foreground">
                {formatDate(view.day)} · <span className="text-foreground">gün {at + 1}</span>/
                {lastIndex + 1}
              </span>
            </div>
          </section>
          <section className="order-3 mt-6 border-t pt-5 xl:order-none">
            <CardHeader title="Son işlemler" description="Seçili güne kadar, en yeniler üstte" />
            {view.feed.length === 0 ? (
              <p className="text-xs text-muted-foreground">Henüz işlem yok.</p>
            ) : (
              <ul className="-mx-1 grid gap-x-6 gap-y-0.5 lg:grid-cols-2">
                {view.feed.map((tr) => (
                  <li
                    key={tr.id}
                    className="flex items-center gap-2.5 rounded-lg px-1 py-1.5 text-xs transition-colors hover:bg-white/[0.03]"
                  >
                    <AgentAvatar
                      id={tr.agentId}
                      name={nameOf(tr.agentId)}
                      className="size-6 text-[9px]"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{nameOf(tr.agentId)}</span>
                      <span className="block text-[11px] num text-muted-foreground">
                        {formatShortDate(tr.day)}
                      </span>
                    </span>
                    <Badge tone={tr.side === 'buy' ? 'up' : 'down'}>
                      {tr.side === 'buy' ? 'AL' : 'SAT'} {tr.asset}
                    </Badge>
                    <span className="w-20 text-right num">
                      {formatNum(tr.quantity * tr.price)} $
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <section
          aria-labelledby="leaderboard-title"
          className="order-2 min-w-0 xl:sticky xl:top-6 xl:order-none xl:border-l xl:pl-6"
        >
          <header className="mb-3 flex items-baseline justify-between gap-3">
            <h2 id="leaderboard-title" className="text-sm font-semibold">
              Lider tablosu
            </h2>
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Trophy className="size-3.5 text-primary" />
              {view.leader.agent.name.replace('LLM · ', '')}
            </span>
          </header>
          {/* Rows stay in a stable DOM order and slide to their rank, so overtakes animate. */}
          <ol className="relative -mx-2" style={{ height: view.runs.length * ROW }}>
            {view.runs.map((r) => {
              const i = view.rank.get(r.agent.id)!
              return (
                <li
                  key={r.agent.id}
                  className="absolute inset-x-0 transition-transform duration-500 ease-[cubic-bezier(0.2,0.8,0.2,1)]"
                  style={{ transform: `translateY(${i * ROW}px)`, height: ROW }}
                >
                  <Link
                    to={`/experiments/${id}/agents/${r.agent.id}`}
                    className={cn(
                      'flex h-full flex-col justify-center rounded-lg px-2 transition-colors hover:bg-white/[0.04]',
                    )}
                  >
                    <span className="flex items-center gap-2.5 text-[13px]">
                      <span className="sr-only">Sıra {i + 1}:</span>
                      <span
                        aria-hidden
                        className={cn(
                          'w-4 text-center text-[11px] num',
                          i === 0 ? 'text-primary' : 'text-muted-foreground',
                        )}
                      >
                        {i + 1}
                      </span>
                      <AgentAvatar
                        id={r.agent.id}
                        name={r.agent.name}
                        className="size-6 text-[9px]"
                        glow={i === 0}
                      />
                      <span className="flex-1 truncate">{r.agent.name}</span>
                      <span className="text-xs num">{formatUsd(r.equity)}</span>
                      <span
                        className={cn(
                          'w-14 text-right text-xs num',
                          r.ret >= 0 ? 'text-up' : 'text-down',
                        )}
                      >
                        {formatPct(r.ret)}
                      </span>
                    </span>
                    <span
                      aria-hidden
                      className="mt-1 ml-[3.25rem] block h-[3px] rounded-full bg-white/[0.06]"
                    >
                      <span
                        className={cn(
                          'block h-full rounded-full transition-[width] duration-500',
                          i === 0 ? 'bg-brand' : r.ret >= 0 ? 'bg-up/60' : 'bg-down/60',
                        )}
                        style={{ width: `${8 + ((r.equity - lo) / span) * 92}%` }}
                      />
                    </span>
                  </Link>
                </li>
              )
            })}
          </ol>
          <p className="mt-3 text-xs text-muted-foreground">Portföy değeri · başlangıç 10.000 $</p>
        </section>
      </div>
    </>
  )
}
