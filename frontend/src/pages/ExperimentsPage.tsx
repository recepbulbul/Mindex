import { Download, FlaskConical, Play, Plus } from 'lucide-react'
import { lazy, Suspense, useMemo } from 'react'
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
import { AssetOrb } from '@/components/identity'
import { Button } from '@/components/ui/button'
import { buttonVariants, segmentClass, segmentedClass } from '@/components/ui/button-variants'
import { Card, EmptyState, ErrorState, Skeleton } from '@/components/ui/primitives'
import { downloadFile } from '@/lib/download'
import { rovingKeyDown } from '@/lib/roving'
import { useSearchParam } from '@/lib/search-param'
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
      <span className="rounded-md bg-primary/12 px-1.5 py-0.5 text-[11px] font-medium num text-primary ring-1 ring-primary/25 ring-inset">
        {code}
      </span>
      {full && <span className="text-xs text-muted-foreground">{text}</span>}
    </span>
  )
}

type Filter = (typeof FILTERS)[number][0]
const FILTERS = [
  ['all', 'Tümü'],
  ['running', 'Çalışıyor'],
  ['completed', 'Tamamlandı'],
  ['draft', 'Taslak'],
] as const
const FILTER_KEYS = FILTERS.map(([key]) => key)
const matches = (f: Filter, e: Experiment) =>
  f === 'all' ||
  (f === 'running' ? e.status === 'running' || e.status === 'queued' : e.status === f)

export function ExperimentsPage() {
  const { user } = useAuth()
  const { data, isPending, error, refetch } = useExperiments()
  const start = useStartExperiment()
  const isResearcher = user?.role === 'researcher'
  const [filter, setFilter] = useSearchParam('status', FILTER_KEYS, 'all')

  const featured =
    data?.find((e) => e.status === 'completed' && e.condition === 'C3') ??
    data?.find((e) => e.status === 'completed')

  const exportYaml = async (id: string) =>
    downloadFile(`${id}.yaml`, await api.text(`/experiments/${id}/export.yaml`), 'application/yaml')

  return (
    <>
      <PageTitle
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

          <div className="mt-20 mb-6 flex flex-wrap items-center justify-between gap-3">
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
                    <span className="rounded-full bg-white/[0.08] px-1.5 text-[10px] num text-muted-foreground">
                      {n}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          <ul className="rounded-2xl px-2 band">
            {data
              .filter((e) => matches(filter, e))
              .map((e) => (
                <li key={e.id} className="border-b">
                  <ExperimentRow
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

/** One experiment as an open row: big name, quiet facts, actions on hover. No box. */
function ExperimentRow({
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
    <div className="group relative grid items-center gap-x-8 gap-y-3 py-6 transition-colors hover:bg-white/[0.025] md:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_auto] md:px-3">
      <div className="min-w-0">
        <h3 className="text-xl font-semibold tracking-[-0.02em]">
          {isDraft ? (
            e.name
          ) : (
            // Stretched link: the whole row opens the live screen.
            <Link
              to={`/experiments/${e.id}/live`}
              className="after:absolute after:inset-0 focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-ring"
            >
              {e.name}
            </Link>
          )}
        </h3>
        <p className="mt-1.5 flex flex-wrap items-center gap-x-3 text-sm text-muted-foreground">
          <ConditionChip condition={e.condition} full />
          <span>{e.mode === 'live' ? 'Canlı' : 'Replay'}</span>
          <span>
            {formatDate(e.startDate)} – {e.endDate ? formatDate(e.endDate) : 'devam ediyor'}
          </span>
        </p>
      </div>

      <div className="flex items-center gap-3">
        <div className="flex -space-x-1.5">
          {e.assets.map((a) => (
            <AssetOrb key={a} asset={a} />
          ))}
        </div>
        <span className="text-sm num text-muted-foreground">
          {e.agentIds.length} ajan, seed {e.seed}
        </span>
      </div>

      <div className="relative z-10 flex items-center justify-end gap-2">
        <StatusBadge status={e.status} />
        {isResearcher && isDraft && (
          <Button size="sm" disabled={starting} onClick={onStart}>
            <Play /> Başlat
          </Button>
        )}
        {!isDraft && (
          <Link
            to={`/experiments/${e.id}/report`}
            className={buttonVariants({ variant: 'ghost', size: 'sm' })}
          >
            Rapor
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
    </div>
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
      className="grid gap-10 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] xl:gap-14"
    >
      <div className="flex flex-col">
        <p className="text-sm text-muted-foreground">
          <ConditionChip condition={experiment.condition} full /> ·{' '}
          {formatDate(experiment.startDate)} –{' '}
          {experiment.endDate ? formatDate(experiment.endDate) : 'devam ediyor'}
        </p>
        <h2
          id="featured-title"
          className="mt-3 text-4xl leading-[1.05] font-semibold tracking-[-0.045em] text-balance sm:text-5xl"
        >
          {experiment.name}
        </h2>

        {summary?.best ? (
          <dl className="mt-10 grid grid-cols-2 divide-x border-y">
            <div className="py-5 pr-6">
              <dt className="eyebrow">Sharpe oranı</dt>
              <dd className="mt-2 text-silver text-4xl font-medium num">
                {formatNum(summary.best.sharpe)}
              </dd>
              <dd className="mt-1 text-xs text-muted-foreground">
                {nameOf(summary.best.agentId).replace('LLM · ', '')}, al-tut{' '}
                {formatNum(summary.r.benchmark.sharpe)}
              </dd>
            </div>
            <div className="py-5 pl-6">
              <dt className="eyebrow">MDD azalması</dt>
              <dd
                className={cn(
                  'mt-2 text-4xl font-medium num',
                  summary.mddCut !== null && summary.mddCut >= 0.3 && 'text-up',
                )}
              >
                {summary.mddCut === null ? '—' : formatPct(summary.mddCut)}
              </dd>
              <dd className="mt-1 text-xs text-muted-foreground">hedef ≥ %30</dd>
            </div>
          </dl>
        ) : (
          <Skeleton className="mt-10 h-28" />
        )}

        <div className="mt-8 flex flex-wrap gap-3 xl:mt-auto xl:pt-8">
          <Link
            to={`/experiments/${experiment.id}/live`}
            className={cn(buttonVariants(), 'h-11 px-5')}
          >
            Canlı yarışı izle
          </Link>
          <Link
            to={`/experiments/${experiment.id}/report`}
            className={cn(buttonVariants({ variant: 'outline' }), 'h-11 px-5')}
          >
            Raporu aç
          </Link>
        </div>
      </div>

      <div className="stage min-w-0">
        <div className="mb-3 flex items-baseline justify-between">
          <p className="text-sm font-medium">Portföy yarışı</p>
          <p className="text-xs text-muted-foreground">ilk 3 LLM ajanı ve BTC al-tut</p>
        </div>
        {lines.length ? (
          <Suspense fallback={<Skeleton className="h-[340px]" />}>
            <MultiLineChart
              lines={lines}
              height={340}
              label="Öne çıkan deneyde en iyi ajanların portföy değeri"
            />
          </Suspense>
        ) : (
          <Skeleton className="h-[340px]" />
        )}
      </div>
    </section>
  )
}
