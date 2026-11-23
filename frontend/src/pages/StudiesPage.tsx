import { Layers, Play, Plus } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { ApiError } from '@/api/client'
import { useAgents, useCreateStudy, useStudies } from '@/api/queries'
import { ASSETS, CONDITIONS, MAX_SEEDS, SMOKE_DAYS, type StudyCreate } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { PageTitle, StatusBadge } from '@/components/common'
import { Button } from '@/components/ui/button'
import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Skeleton,
} from '@/components/ui/primitives'
import { formatDate } from '@/lib/utils'

// The validation half-year (the test window is sealed) and the comparison's agents.
const DEFAULTS = {
  startDate: '2025-10-01',
  endDate: '2026-03-31',
  agentIds: [
    'buy-hold-btc',
    'equal-weight',
    'llm-momentum',
    'llm-mean-reversion',
    'llm-sentiment',
    'llm-risk-averse',
  ],
}

const reasons = (err: Error) =>
  [err.message, ...(err instanceof ApiError ? Object.values(err.fields) : [])].join(' ')

export default function StudiesPage() {
  const { user } = useAuth()
  const studies = useStudies()
  const isResearcher = user?.role === 'researcher'

  return (
    <>
      <PageTitle
        title="Çalışmalar"
        subtitle="Bir çalışma, aynı dönem, ajan ve varlıklarla her koşulu (C0–C3) her seed için koşturur ve koşulları güven aralıklarıyla karşılaştırır."
      />
      {isResearcher && <CreateStudy />}
      {studies.error ? (
        <ErrorState error={studies.error} onRetry={() => void studies.refetch()} />
      ) : !studies.data ? (
        <Skeleton className="h-40" />
      ) : studies.data.length === 0 ? (
        <Card>
          <EmptyState icon={<Layers />} title="Henüz çalışma yok">
            {isResearcher
              ? 'Önce kısa bir smoke çalışmasıyla bütün koşulları deneyin.'
              : 'Bir araştırmacı çalışma oluşturduğunda burada görünür.'}
          </EmptyState>
        </Card>
      ) : (
        <ul className="space-y-2" aria-label="Çalışmalar">
          {studies.data.map((s) => {
            const done = s.runs.filter((r) => r.status === 'completed').length
            return (
              <li key={s.id}>
                <Link
                  to={`/studies/${s.id}`}
                  className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border bg-card p-4 transition-colors hover:border-border-strong"
                >
                  <span className="font-medium">{s.name}</span>
                  <StatusBadge status={s.status} />
                  {s.smoke && <Badge tone="neutral">smoke</Badge>}
                  <span className="text-xs text-muted-foreground">
                    {formatDate(s.startDate)} – {formatDate(s.endDate)} · {s.seeds.length} seed
                  </span>
                  <span className="ml-auto text-xs num text-muted-foreground">
                    {done}/{s.runs.length} koşu tamamlandı
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </>
  )
}

function CreateStudy() {
  const id = useId()
  const navigate = useNavigate()
  const agents = useAgents()
  const create = useCreateStudy()
  const [name, setName] = useState('C0–C3 karşılaştırması')
  const [seeds, setSeeds] = useState(5)
  const [smoke, setSmoke] = useState(true)
  const available = new Set(agents.data?.filter((a) => a.available).map((a) => a.id))
  const agentIds = DEFAULTS.agentIds.filter((a) => !agents.data || available.has(a))
  const runs = (smoke ? 1 : seeds) * CONDITIONS.length

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const body: StudyCreate = {
      name,
      startDate: DEFAULTS.startDate,
      endDate: DEFAULTS.endDate,
      assets: [...ASSETS],
      agentIds,
      seeds: Array.from({ length: seeds }, (_, i) => i + 1),
      smoke,
      commissionRate: 0.001,
      slippageBps: 5,
    }
    create.mutate(body, { onSuccess: (s) => void navigate(`/studies/${s.id}`) })
  }

  return (
    <Card className="mb-5">
      <CardHeader
        title="Yeni çalışma"
        description={`Doğrulama dönemi (${formatDate(DEFAULTS.startDate)} – ${formatDate(DEFAULTS.endDate)}), beş varlık, dört LLM ajanı ve iki kural ajanı. Test dönemi mühürlüdür.`}
      />
      <form
        onSubmit={submit}
        className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_8rem_auto] sm:items-end"
      >
        <Field label="Ad" htmlFor={`${id}-name`}>
          <Input id={`${id}-name`} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Seed sayısı" htmlFor={`${id}-seeds`}>
          <Input
            id={`${id}-seeds`}
            type="number"
            min={1}
            max={MAX_SEEDS}
            value={seeds}
            disabled={smoke}
            onChange={(e) => setSeeds(Math.max(1, Math.min(MAX_SEEDS, Number(e.target.value))))}
          />
        </Field>
        <Button type="submit" disabled={create.isPending}>
          <Plus /> {runs} deney oluştur
        </Button>
        <label className="flex cursor-pointer items-center gap-2 text-sm sm:col-span-3">
          <input type="checkbox" checked={smoke} onChange={(e) => setSmoke(e.target.checked)} />
          Smoke: ilk {SMOKE_DAYS} gün, tek seed (tam koşudan önce hızlı deneme)
        </label>
        {create.error && (
          <p role="alert" className="text-sm text-down sm:col-span-3">
            Oluşturulamadı: {reasons(create.error)}
          </p>
        )}
      </form>
      <p className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground">
        <Play className="size-3" /> Oluşturduktan sonra çalışma sayfasından başlatın; aynı iş komut
        satırından da yapılır: <code>mindex study create --smoke</code>
      </p>
    </Card>
  )
}
