import { Download, Printer } from 'lucide-react'
import { useMemo } from 'react'
import { Link, useParams } from 'react-router'
import { useAgents, useExperiment, useReport, useTimeline } from '@/api/queries'
import { ConditionComparison } from '@/components/condition-comparison'
import { MultiLineChart } from '@/components/charts/charts'
import { ExperimentActions } from '@/app/ExperimentLayout'
import { AgentAvatar } from '@/components/identity'
import { downloadFile } from '@/lib/download'
import { Button } from '@/components/ui/button'
import {
  Badge,
  Card,
  CardHeader,
  ErrorState,
  Skeleton,
  Stat,
  StatGrid,
  Table,
} from '@/components/ui/primitives'
import { reportToCsv } from '@/lib/report'
import { agentColor } from '@/lib/identity'
import { cn, formatNum, formatPct } from '@/lib/utils'

export default function ReportPage() {
  const { id = '' } = useParams()
  const experiment = useExperiment(id)
  const report = useReport(id)
  const timeline = useTimeline(id, experiment.data?.status !== 'draft')
  const agents = useAgents()
  const nameOf = (aid: string) => agents.data?.find((a) => a.id === aid)?.name ?? aid

  const lines = useMemo(
    () =>
      timeline.data?.runs.map((r) => ({
        id: r.agent.id,
        name: r.agent.name.replace('LLM · ', ''),
        points: r.equity.map((p) => ({ time: p.day, value: p.equity })),
        color: agentColor(r.agent.id),
      })) ?? [],
    [timeline.data],
  )

  if (report.error) return <ErrorState error={report.error} onRetry={() => void report.refetch()} />
  if (!report.data || !experiment.data) return <Skeleton className="h-[480px]" />

  const r = report.data
  const isLlm = (aid: string) => agents.data?.find((a) => a.id === aid)?.kind === 'llm'
  const llm = r.agents.filter((a) => isLlm(a.agentId))
  const best = [...llm].sort((a, b) => b.sharpe - a.sharpe)[0]
  const mddReduction =
    best && r.benchmark.maxDrawdown > 0 ? 1 - best.maxDrawdown / r.benchmark.maxDrawdown : null

  return (
    <>
      <ExperimentActions>
        <>
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              downloadFile(`mindex-${id}-report.csv`, reportToCsv(r, nameOf), 'text/csv')
            }
          >
            <Download /> CSV
          </Button>
          <Button size="sm" variant="ghost" onClick={() => window.print()}>
            <Printer /> PDF
          </Button>
        </>
      </ExperimentActions>

      <StatGrid className="mb-4 grid-cols-2 md:grid-cols-4">
        <Stat
          label="En iyi LLM ajanı (Sharpe)"
          value={best ? nameOf(best.agentId).replace('LLM · ', '') : '—'}
        />
        <Stat
          label="Sharpe · en iyi / BTC al-tut"
          value={`${formatNum(best?.sharpe ?? 0)} / ${formatNum(r.benchmark.sharpe)}`}
        />
        <Stat
          label="MDD azalması (hedef ≥ %30)"
          value={mddReduction === null ? '—' : formatPct(mddReduction)}
          tone={mddReduction !== null && mddReduction >= 0.3 ? 'up' : 'down'}
        />
        <Stat label="Sürü korelasyonu (LLM)" value={formatNum(r.herdCorrelation)} />
      </StatGrid>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title="Ajan metrikleri" />
          <Table>
            <thead>
              <tr>
                <th>Ajan</th>
                <th className="text-right">Getiri</th>
                <th className="text-right">Sharpe</th>
                <th className="text-right">MDD</th>
                <th className="text-right">İşlem</th>
              </tr>
            </thead>
            <tbody>
              {[...r.agents]
                .sort((a, b) => b.sharpe - a.sharpe)
                .map((a) => (
                  <tr
                    key={a.agentId}
                    className={cn(a.agentId === best?.agentId && 'bg-primary/[0.06]')}
                  >
                    <td className="whitespace-nowrap">
                      <span className="inline-flex items-center gap-2 align-middle">
                        <AgentAvatar
                          id={a.agentId}
                          name={nameOf(a.agentId)}
                          className="size-6 text-[9px]"
                        />
                        {nameOf(a.agentId)}
                      </span>
                      {a.agentId === best?.agentId && (
                        <Badge
                          tone="warn"
                          className="ml-2 border-0 bg-primary/15 text-primary ring-primary/30"
                        >
                          en iyi
                        </Badge>
                      )}
                    </td>
                    <td
                      className={cn('text-right num', a.totalReturn >= 0 ? 'text-up' : 'text-down')}
                    >
                      {formatPct(a.totalReturn)}
                    </td>
                    <td className="text-right num">{formatNum(a.sharpe)}</td>
                    <td className="text-right num">{formatPct(-a.maxDrawdown)}</td>
                    <td className="text-right num">{a.trades}</td>
                  </tr>
                ))}
            </tbody>
          </Table>
        </Card>

        <section className="stage">
          <CardHeader title="Portföy değerleri" description="Tüm ajanlar, başlangıç 10.000 $" />
          <MultiLineChart
            lines={lines}
            height={340}
            label="Ajanların portföy değeri zaman serisi"
          />
        </section>
      </div>

      {r.conditions.length > 0 && (
        <ConditionComparison className="mt-4" conditions={r.conditions} />
      )}
      {experiment.data?.studyId && (
        <p className="mt-3 text-sm print:hidden">
          <Link to={`/studies/${experiment.data.studyId}`} className="text-primary underline">
            Bu deneyin çalışması: tüm koşullar, seed'ler ve farkların güven aralıkları
          </Link>
        </p>
      )}
    </>
  )
}
