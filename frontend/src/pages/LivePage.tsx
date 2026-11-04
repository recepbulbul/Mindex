import {
  Activity,
  Clock,
  Pause,
  Play,
  Radio,
  RotateCcw,
  SkipForward,
  TrendingDown,
  TrendingUp,
  Trophy,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import { useExperiment, useTimeline } from '@/api/queries'
import { CONDITION_LABELS, type Asset } from '@/api/types'
import { CandleChart, type TradeMarker } from '@/components/charts/charts'
import { PageTitle, RegimeBadge, StatusBadge } from '@/components/common'
import { AgentAvatar, AssetOrb, Sparkline } from '@/components/identity'
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
const SPARK_DAYS = 30

export default function LivePage() {
  const { id = '' } = useParams()
  const experiment = useExperiment(id)
  const isDraft = experiment.data?.status === 'draft'
  const timeline = useTimeline(id, experiment.isSuccess && !isDraft)

  const [asset, setAsset] = useState<Asset>('BTC')
  const [agentFilter, setAgentFilter] = useState('llm-momentum')
  const [cursor, setCursor] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(5)

  const lastIndex = (timeline.data?.days.length ?? 1) - 1
  // Live experiments open at the latest tick; replays open at day 30 so there is history to see.
  const at = cursor ?? (experiment.data?.mode === 'live' ? lastIndex : Math.min(30, lastIndex))

  useEffect(() => {
    if (!playing) return
    const timer = setInterval(() => {
      setCursor((c) => {
        const next = (c ?? at) + 1
        if (next >= lastIndex) setPlaying(false)
        return Math.min(next, lastIndex)
      })
    }, BASE_TICK_MS / speed)
    return () => clearInterval(timer)
  }, [playing, speed, lastIndex, at])

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
      const closes = t.candles[a].slice(Math.max(0, at - SPARK_DAYS), at + 1).map((c) => c.close)
      const last = closes.at(-1)!
      return { asset: a, price: last, change: last / (closes.at(-2) ?? last) - 1, closes }
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
      <>
        <PageTitle
          eyebrow={
            <>
              <Activity /> Canlı borsa
            </>
          }
          title={experiment.data!.name}
        />
        <Card>
          <EmptyState icon={<Clock />} title="Bu deney henüz başlatılmadı.">
            <Link to="/experiments" className="text-primary underline-offset-4 hover:underline">
              Deneylere dön
            </Link>
          </EmptyState>
        </Card>
      </>
    )
  if (timeline.error)
    return <ErrorState error={timeline.error} onRetry={() => void timeline.refetch()} />
  if (!view || !experiment.data) return <Skeleton className="h-[480px]" />

  const exp = experiment.data
  const isLive = exp.mode === 'live'
  const equities = view.runs.map((r) => r.equity)
  const lo = Math.min(...equities)
  const span = Math.max(...equities) - lo || 1
  const nameOf = (aid: string) => view.runs.find((r) => r.agent.id === aid)?.agent.name ?? aid
  const progress = lastIndex > 0 ? (at / lastIndex) * 100 : 100

  return (
    <>
      <PageTitle
        eyebrow={
          <>
            <Activity /> Canlı borsa
          </>
        }
        title={exp.name}
        subtitle={`${CONDITION_LABELS[exp.condition]} · seed ${exp.seed} · ${exp.agentIds.length} ajan`}
        actions={
          <div className="flex items-center gap-2">
            {isLive && (
              <Badge tone="up" className="gap-1.5">
                <Radio className="size-3 animate-pulse" /> Binance akışı bağlı (sahte)
              </Badge>
            )}
            <StatusBadge status={exp.status} />
          </div>
        }
      />

      {/* Ticker strip: every traded asset at the current simulation day; picks the chart. */}
      <div
        role="tablist"
        aria-label="Varlık"
        onKeyDown={rovingKeyDown}
        tabIndex={-1}
        className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5"
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
                  'group relative overflow-hidden rounded-2xl border glass p-3.5 text-left transition-all duration-300',
                  active
                    ? 'border-primary/40 bg-elevated shadow-[inset_0_1px_0_oklch(1_0_0/0.08),inset_0_-2px_0_var(--primary)]'
                    : 'hover:-translate-y-0.5 hover:border-border-strong',
                )}
              >
                <span className="flex items-center gap-2">
                  <AssetOrb asset={tk.asset} className="ring-0" />
                  <span className="text-sm font-semibold">{tk.asset}</span>
                  <span className="text-[11px] text-muted-foreground">/USDT</span>
                  <span
                    className={cn(
                      'ml-auto num text-[11px]',
                      tk.change >= 0 ? 'text-up' : 'text-down',
                    )}
                  >
                    {formatPct(tk.change)}
                  </span>
                </span>
                <span className="mt-2 block num text-lg font-medium tracking-tight">
                  {formatPrice(tk.price)}
                </span>
                <Sparkline values={tk.closes} className="mt-1 h-7" />
              </button>
            )
          })}
      </div>

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        {/* Below xl the wrapper dissolves so the order is chart, leaderboard, trades. */}
        <div className="contents xl:grid xl:min-w-0 xl:gap-4">
          <Card className="order-1 overflow-hidden p-0 xl:order-none">
            <div className="flex flex-wrap items-center gap-x-5 gap-y-3 px-5 pt-5">
              <div className="flex items-center gap-3">
                <AssetOrb asset={asset} className="size-9 text-xs ring-0" />
                <div>
                  <p className="text-xs text-muted-foreground">{asset}/USDT · günlük</p>
                  <div className="flex items-baseline gap-2.5">
                    <span className="num text-[1.75rem] leading-tight font-medium tracking-tight">
                      {formatPrice(view.price)}
                    </span>
                    <span
                      className={cn(
                        'inline-flex items-center gap-1 num text-sm',
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

            <div className="px-2 pt-2">
              <CandleChart
                candles={view.candles}
                markers={view.markers}
                height={420}
                label={`${asset}/USDT günlük mum grafiği`}
              />
            </div>

            {/* Transport: play/pause, speed, scrubber with a gradient progress fill. */}
            <div className="flex flex-wrap items-center gap-3 border-t bg-black/20 px-5 py-3.5">
              <div className="flex items-center gap-1">
                <Button
                  size="icon"
                  aria-label={playing ? 'Duraklat' : 'Oynat'}
                  onClick={() => setPlaying((p) => !p)}
                  disabled={at >= lastIndex}
                  className="size-10 rounded-full"
                >
                  {playing ? <Pause /> : <Play />}
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
              <span className="num text-xs text-muted-foreground">
                {formatDate(view.day)} · <span className="text-foreground">gün {at + 1}</span>/
                {lastIndex + 1}
              </span>
            </div>
          </Card>
          <Card className="order-3 xl:order-none">
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
                      <span className="block num text-[11px] text-muted-foreground">
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
          </Card>
        </div>

        <div className="order-2 min-w-0 xl:sticky xl:top-6 xl:order-none">
          <Card>
            <CardHeader
              title="Lider tablosu"
              description="Portföy değeri · başlangıç 10.000 $"
              action={
                <span className="flex items-center gap-1.5 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] text-primary ring-1 ring-primary/25">
                  <Trophy className="size-3" /> {view.leader.agent.name.replace('LLM · ', '')}
                </span>
              }
            />
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
                        'flex h-full flex-col justify-center rounded-xl px-2 transition-colors hover:bg-white/[0.05]',
                        i === 0 && 'bg-primary/[0.07]',
                      )}
                    >
                      <span className="flex items-center gap-2.5 text-[13px]">
                        <span className="sr-only">Sıra {i + 1}:</span>
                        <span
                          aria-hidden
                          className={cn(
                            'w-4 text-center num text-[11px]',
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
                        <span className="num text-xs">{formatUsd(r.equity)}</span>
                        <span
                          className={cn(
                            'w-14 text-right num text-xs',
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
          </Card>
        </div>
      </div>
    </>
  )
}
