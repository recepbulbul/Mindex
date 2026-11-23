import { ChevronLeft, Play } from 'lucide-react'
import { Link, useParams } from 'react-router'
import { ApiError } from '@/api/client'
import { useStartStudy, useStudy, useStudyComparison } from '@/api/queries'
import { CONDITION_LABELS, CONDITIONS, type StudyRun } from '@/api/types'
import { useAuth } from '@/auth/AuthContext'
import { PageTitle, StatusBadge } from '@/components/common'
import { ConditionComparison, ConditionDifferences } from '@/components/condition-comparison'
import { Button } from '@/components/ui/button'
import { Badge, Card, CardHeader, ErrorState, Skeleton, Table } from '@/components/ui/primitives'
import { formatDate } from '@/lib/utils'

const reasons = (err: Error) =>
  [err.message, ...(err instanceof ApiError ? Object.values(err.fields) : [])].join(' ')

export default function StudyPage() {
  const { id = '' } = useParams()
  const { user } = useAuth()
  const study = useStudy(id)
  const anyDone = study.data?.runs.some((r) => r.status === 'completed') ?? false
  const comparison = useStudyComparison(id, anyDone)
  const start = useStartStudy()

  if (study.error) return <ErrorState error={study.error} onRetry={() => void study.refetch()} />
  if (!study.data) return <Skeleton className="h-96" />
  const s = study.data
  const startable = s.runs.some((r) => r.status === 'draft' || r.status === 'failed')
  const done = s.runs.filter((r) => r.status === 'completed').length

  return (
    <>
      <PageTitle
        eyebrow={
          <Link to="/studies" className="flex items-center gap-1">
            <ChevronLeft /> Çalışmalar
          </Link>
        }
        title={s.name}
        subtitle={`${formatDate(s.startDate)} – ${formatDate(s.endDate)} · ${s.assets.length} varlık · ${s.agentIds.length} ajan · seed ${s.seeds.join(', ')}`}
        actions={
          <>
            {s.smoke && <Badge tone="neutral">smoke</Badge>}
            <StatusBadge status={s.status} />
            {user?.role === 'researcher' && startable && (
              <Button size="sm" disabled={start.isPending} onClick={() => start.mutate(s.id)}>
                <Play /> {done === 0 ? 'Başlat' : 'Kalanları başlat'}
              </Button>
            )}
          </>
        }
      />
      {start.error && (
        <p role="alert" className="mb-4 text-sm text-down">
          Başlatılamadı: {reasons(start.error)}
        </p>
      )}

      <Card className="mb-4">
        <CardHeader
          title="Koşular"
          description={`${done}/${s.runs.length} tamamlandı. Her hücre bir deney; tıklayınca canlı ekranı açılır.`}
        />
        <RunGrid runs={s.runs} seeds={s.seeds} />
      </Card>

      {!anyDone ? (
        <p className="text-sm text-muted-foreground">
          Karşılaştırma, ilk koşu tamamlanınca burada görünür.
        </p>
      ) : comparison.error ? (
        <ErrorState error={comparison.error} onRetry={() => void comparison.refetch()} />
      ) : !comparison.data ? (
        <Skeleton className="h-64" />
      ) : (
        <div className="space-y-4">
          {!comparison.data.complete && (
            <p className="text-sm text-warn" role="status">
              Kısmi sonuç: yalnızca tamamlanan koşular sayıldı.
            </p>
          )}
          <ConditionComparison conditions={comparison.data.conditions} />
          {comparison.data.differences.length > 0 && (
            <ConditionDifferences differences={comparison.data.differences} />
          )}
          <p className="text-xs text-muted-foreground">
            {comparison.data.days} günlük getiri, {comparison.data.blockLength} günlük bloklar,{' '}
            {comparison.data.resamples} yeniden örnekleme (sabit seed: aynı veriyle aynı aralık).
          </p>
        </div>
      )}
    </>
  )
}

function RunGrid({ runs, seeds }: { runs: StudyRun[]; seeds: number[] }) {
  const cell = (seed: number, condition: string) =>
    runs.find((r) => r.seed === seed && r.condition === condition)
  return (
    <Table>
      <thead>
        <tr>
          <th>Seed</th>
          {CONDITIONS.map((c) => (
            <th key={c} className="whitespace-nowrap">
              {CONDITION_LABELS[c].split(' ·')[0]}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {seeds.map((seed) => (
          <tr key={seed}>
            <th scope="row" className="num">
              {seed}
            </th>
            {CONDITIONS.map((c) => {
              const r = cell(seed, c)
              return (
                <td key={c}>
                  {r ? (
                    <Link
                      to={`/experiments/${r.experimentId}/live`}
                      aria-label={`${CONDITION_LABELS[c]}, seed ${seed}: ${r.status}`}
                      className="inline-flex"
                    >
                      <StatusBadge status={r.status} />
                    </Link>
                  ) : (
                    '—'
                  )}
                </td>
              )
            })}
          </tr>
        ))}
      </tbody>
    </Table>
  )
}
