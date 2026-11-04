import {
  Activity,
  ArrowRight,
  BarChart3,
  CalendarRange,
  Download,
  FlaskConical,
  Play,
  Plus,
  Sparkles,
  Users,
} from 'lucide-react'
import { lazy, Suspense, useMemo, useState } from 'react'
import { Link } from 'react-router'
import { api } from '@/api/client'
import {
  useAgents,
  useExperiments,
  useReport,
  useStartExperiment,
  useTimeline,
} from '@/api/queries'
import { CONDITION_LABELS, type Condition, type Experiment } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { PageTitle, StatusBadge } from '@/components/common'
import { AgentAvatar, AssetOrb } from '@/components/identity'
import { Button } from '@/components/ui/button'
import { buttonVariants, segmentClass, segmentedClass } from '@/components/ui/button-variants'
import { Card, EmptyState, ErrorState, Skeleton, Stat } from '@/components/ui/primitives'
import { downloadFile } from '@/lib/download'
import { rovingKeyDown } from '@/lib/roving'
import { agentColor } from '@/lib/identity'
import { cn, formatDate, formatNum, formatPct } from '@/lib/utils'

// The chart library is the largest dependency; keep it out of the first screen's bundle.
const MultiLineChart = lazy(() =>
  import('@/components/charts/charts').then((m) => ({ default: m.MultiLineChart })),
)

/** "C3 · Güven ağırlıklı forum" → code chip + description. */
function ConditionChip({ condition, full }: { condition: Condition; full?: boolean }) {
  const [code, text] = CONDITION_LABELS[condition].split(' · ')
  return (
    <span className="inline-flex items-center gap-2" title={CONDITION_LABELS[condition]}>
      <span className="rounded-md bg-primary/12 px-1.5 py-0.5 num text-[11px] font-medium text-primary ring-1 ring-primary/25 ring-inset">
        {code}
      </span>
      {full && <span className="text-xs text-muted-foreground">{text}</span>}
    </span>
  )
}

type Filter = 'all' | 'running' | 'completed' | 'draft'
const FILTERS: [Filter, string][] = [
  ['all', 'Tümü'],
  ['running', 'Çalışıyor'],
  ['completed', 'Tamamlandı'],
  ['draft', 'Taslak'],
]
const matches = (f: Filter, e: Experiment) =>
  f === 'all' ||
  (f === 'running' ? e.status === 'running' || e.status === 'queued' : e.status === f)

export function ExperimentsPage() {
  const { user } = useAuth()
  const { data, isPending, error, refetch } = useExperiments()
  const start = useStartExperiment()
  const isResearcher = user?.role === 'researcher'
  const [filter, setFilter] = useState<Filter>('all')

  const featured =
    data?.find((e) => e.status === 'completed' && e.condition === 'C3') ??
    data?.find((e) => e.status === 'completed')

  const exportYaml = async (id: string) =>
    downloadFile(`${id}.yaml`, await api.text(`/experiments/${id}/export.yaml`), 'application/yaml')

  return (
    <>
      <PageTitle
        eyebrow={
          <>
            <FlaskConical /> Çalışma alanı
          </>
        }
        title="Deneyler"
        subtitle="Replay ve canlı paper-trading deneyleri. Bir deneyi açarak ajanların yarışını canlı izleyin."
        actions={
          isResearcher && (
            <Link to="/experiments/new" className={buttonVariants()}>
              <Plus /> Yeni deney
            </Link>
          )
        }
      />

      {isPending ? (
        <div className="space-y-4">
          <Skeleton className="h-80" />
          <Skeleton className="h-56" />
        </div>
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : data.length === 0 ? (
        <Card>
          <EmptyState icon={<FlaskConical />} title="Henüz deney yok">
            {isResearcher
              ? 'Yeni deney düğmesiyle ilk deneyinizi tanımlayın.'
              : 'Bir araştırmacı deney tanımladığında burada görünecek.'}
          </EmptyState>
        </Card>
      ) : (
        <>
          {featured && <FeaturedExperiment experiment={featured} />}

          <div className="mt-10 mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-3xl font-semibold tracking-[-0.04em]">Tüm deneyler</h2>
            <div
              role="tablist"
              aria-label="Duruma göre filtrele"
              className={segmentedClass}
              onKeyDown={rovingKeyDown}
              tabIndex={-1}
            >
              {FILTERS.map(([key, label]) => {
                const n = data.filter((e) => matches(key, e)).length
                return (
                  <button
                    key={key}
                    type="button"
                    role="tab"
                    aria-selected={filter === key}
                    tabIndex={filter === key ? 0 : -1}
                    onClick={() => setFilter(key)}
                    className={cn(segmentClass(filter === key), 'flex items-center gap-1.5')}
                  >
                    {label}
                    <span className="rounded-full bg-white/[0.08] px-1.5 num text-[10px] text-muted-foreground">
                      {n}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {data
              .filter((e) => matches(filter, e))
              .map((e, i) => (
                <li key={e.id} className="animate-rise" style={{ animationDelay: `${i * 50}ms` }}>
                  <ExperimentCard
                    e={e}
                    isResearcher={isResearcher}
                    starting={start.isPending}
                    onStart={() => start.mutate(e.id)}
                    onExport={() => void exportYaml(e.id)}
                  />
                </li>
              ))}
          </ul>
        </>
      )}
    </>
  )
}

function ExperimentCard({
  e,
  isResearcher,
  starting,
  onStart,
  onExport,
}: {
  e: Experiment
  isResearcher: boolean
  starting: boolean
  onStart: () => void
  onExport: () => void
}) {
  const isDraft = e.status === 'draft'
  return (
    <Card
      className={cn(
        'group flex h-full flex-col transition-transform duration-300 hover:-translate-y-0.5',
        isDraft && 'border-dashed',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <ConditionChip condition={e.condition} full />
        <StatusBadge status={e.status} />
      </div>

      <h3 className="mt-4 text-[17px] leading-snug font-semibold tracking-tight">
        {isDraft ? (
          e.name
        ) : (
          // Stretched link: the whole card opens the live screen.
          <Link
            to={`/experiments/${e.id}/live`}
            className="after:absolute after:inset-0 after:rounded-2xl focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-ring"
          >
            {e.name}
          </Link>
        )}
      </h3>

      <div className="mt-3 flex items-center gap-3">
        <div className="flex -space-x-1.5">
          {e.assets.map((a) => (
            <AssetOrb key={a} asset={a} />
          ))}
        </div>
        <span className="text-xs text-muted-foreground">{e.assets.join(' · ')}</span>
      </div>

      <dl className="mt-5 grid grid-cols-3 gap-3 border-t pt-4 text-xs">
        <div className="col-span-2">
          <dt className="flex items-center gap-1 text-muted-foreground">
            <CalendarRange className="size-3" /> Dönem
          </dt>
          <dd className="mt-1 font-medium">
            {formatDate(e.startDate)} – {e.endDate ? formatDate(e.endDate) : 'devam ediyor'}
          </dd>
          <dd className="text-[11px] text-muted-foreground">
            {e.mode === 'live' ? 'Canlı (paper)' : 'Replay'}
          </dd>
        </div>
        <div>
          <dt className="flex items-center gap-1 text-muted-foreground">
            <Users className="size-3" /> Ajan · seed
          </dt>
          <dd className="mt-1 num font-medium">
            {e.agentIds.length} · {e.seed}
          </dd>
        </div>
      </dl>

      <div className="relative z-10 mt-auto flex items-center justify-end gap-1 pt-4">
        {isResearcher && isDraft && (
          <Button size="sm" disabled={starting} onClick={onStart} className="mr-auto">
            <Play /> Başlat
          </Button>
        )}
        {!isDraft && (
          <Link
            to={`/experiments/${e.id}/report`}
            className={buttonVariants({ variant: 'ghost', size: 'sm' })}
          >
            <BarChart3 /> Rapor
          </Link>
        )}
        <Button
          size="sm"
          variant="ghost"
          title="YAML olarak indir"
          aria-label={`${e.name} YAML olarak indir`}
          onClick={onExport}
        >
          <Download />
        </Button>
      </div>
    </Card>
  )
}

/** Hero panel: the headline result of the main experiment, with its equity race. */
function FeaturedExperiment({ experiment }: { experiment: Experiment }) {
  const report = useReport(experiment.id)
  const timeline = useTimeline(experiment.id)
  const agents = useAgents()
  const nameOf = (id: string) => agents.data?.find((a) => a.id === id)?.name ?? id

  const summary = useMemo(() => {
    const r = report.data
    if (!r || !agents.data) return null
    const llmIds = new Set(agents.data.filter((a) => a.kind === 'llm').map((a) => a.id))
    const llm = r.agents.filter((a) => llmIds.has(a.agentId)).sort((a, b) => b.sharpe - a.sharpe)
    const best = llm[0]
    const mddCut =
      best && r.benchmark.maxDrawdown > 0 ? 1 - best.maxDrawdown / r.benchmark.maxDrawdown : null
    return { best, mddCut, r, top: llm.slice(0, 3).map((a) => a.agentId) }
  }, [report.data, agents.data])

  const lines = useMemo(() => {
    if (!timeline.data || !summary) return []
    const wanted = [...summary.top, 'buy-hold-btc']
    return timeline.data.runs
      .filter((run) => wanted.includes(run.agent.id))
      .sort((a, b) => wanted.indexOf(a.agent.id) - wanted.indexOf(b.agent.id))
      .map((run) => ({
        id: run.agent.id,
        name: run.agent.name.replace('LLM · ', ''),
        points: run.equity.map((p) => ({ time: p.day, value: p.equity })),
        color: agentColor(run.agent.id),
      }))
  }, [timeline.data, summary])

  return (
    <section
      aria-labelledby="featured-title"
      className="relative overflow-hidden rounded-3xl border glass p-6 sm:p-8"
    >
      <div className="relative grid gap-8 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="flex flex-col">
          <span className="inline-flex w-fit items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 text-[11px] font-medium text-primary">
            <Sparkles className="size-3.5" /> Öne çıkan sonuç
          </span>
          <h2
            id="featured-title"
            className="mt-4 text-headline text-3xl leading-tight font-semibold tracking-[-0.04em] sm:text-[2.5rem]"
          >
            {experiment.name}
          </h2>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <ConditionChip condition={experiment.condition} full />
            <span>
              {formatDate(experiment.startDate)} –{' '}
              {experiment.endDate ? formatDate(experiment.endDate) : 'devam ediyor'}
            </span>
          </div>

          {summary?.best ? (
            <div className="mt-7 grid grid-cols-3 gap-4">
              <div className="col-span-3 flex items-center gap-3 sm:col-span-1 sm:flex-col sm:items-start">
                <AgentAvatar
                  id={summary.best.agentId}
                  name={nameOf(summary.best.agentId)}
                  className="size-11 text-sm"
                  glow
                />
                <div>
                  <p className="eyebrow">En iyi LLM ajanı</p>
                  <p className="mt-0.5 text-sm font-semibold">
                    {nameOf(summary.best.agentId).replace('LLM · ', '')}
                  </p>
                </div>
              </div>
              <Stat
                size="lg"
                label="Sharpe · BTC"
                value={formatNum(summary.best.sharpe)}
                hint={`al-tut ${formatNum(summary.r.benchmark.sharpe)}`}
              />
              <Stat
                size="lg"
                label="MDD azalması"
                value={summary.mddCut === null ? '—' : formatPct(summary.mddCut)}
                hint="hedef ≥ %30"
                tone={summary.mddCut !== null && summary.mddCut >= 0.3 ? 'up' : undefined}
              />
            </div>
          ) : (
            <Skeleton className="mt-7 h-20" />
          )}

          <div className="mt-auto flex flex-wrap gap-2 pt-7">
            <Link to={`/experiments/${experiment.id}/live`} className={buttonVariants()}>
              <Activity /> Canlı yarışı izle <ArrowRight />
            </Link>
            <Link
              to={`/experiments/${experiment.id}/report`}
              className={buttonVariants({ variant: 'outline' })}
            >
              <BarChart3 /> Raporu aç
            </Link>
          </div>
        </div>

        <div className="min-w-0 rounded-2xl border bg-black/20 p-4">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm font-medium">Portföy yarışı</p>
            <p className="text-xs text-muted-foreground">ilk 3 LLM ajanı ve BTC al-tut</p>
          </div>
          {lines.length ? (
            <Suspense fallback={<Skeleton className="h-[280px]" />}>
              <MultiLineChart
                lines={lines}
                height={250}
                label="Öne çıkan deneyde en iyi ajanların portföy değeri"
              />
            </Suspense>
          ) : (
            <Skeleton className="h-[280px]" />
          )}
        </div>
      </div>
    </section>
  )
}
