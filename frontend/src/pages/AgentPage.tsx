import {
  ArrowLeft,
  BrainCircuit,
  ChevronRight,
  MessageSquareText,
  RotateCw,
  ShieldAlert,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import { useAgentDetail, useAgents, useForum, useMemories, useReport } from '@/api/queries'
import type { Decision } from '@/api/types'
import { MultiLineChart } from '@/components/charts/charts'
import { RegimeBadge } from '@/components/common'
import { AgentAvatar } from '@/components/identity'
import { Button } from '@/components/ui/button'
import {
  Badge,
  Card,
  CardHeader,
  ErrorState,
  Skeleton,
  Stat,
  Table,
} from '@/components/ui/primitives'
import { agentColor } from '@/lib/identity'
import { dailyReturns, maxDrawdown, sharpeRatio } from '@/lib/metrics'
import { cn, formatDate, formatNum, formatPct, formatUsd } from '@/lib/utils'

const PAGE_SIZE = 15

export default function AgentPage() {
  const { id = '', agentId = '' } = useParams()
  const detail = useAgentDetail(id, agentId)
  const agents = useAgents()
  const isLlm = detail.data?.agent.kind === 'llm'
  const memories = useMemories(id, { agent: agentId })
  const forum = useForum(id)
  const report = useReport(id)
  const [page, setPage] = useState(0)
  const [open, setOpen] = useState<string | null>(null)

  const stats = useMemo(() => {
    const eq = detail.data?.equity.map((p) => p.equity) ?? []
    if (eq.length < 2) return null
    return {
      equity: eq.at(-1)!,
      ret: eq.at(-1)! / eq[0]! - 1,
      sharpe: sharpeRatio(dailyReturns(eq)),
      mdd: maxDrawdown(eq),
    }
  }, [detail.data])

  const lines = useMemo(
    () =>
      detail.data
        ? [
            {
              id: agentId,
              name: detail.data.agent.name,
              points: detail.data.equity.map((p) => ({ time: p.day, value: p.equity })),
              color: agentColor(agentId),
            },
          ]
        : [],
    [detail.data, agentId],
  )

  if (detail.error) return <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />
  if (!detail.data) return <Skeleton className="h-[480px]" />

  const { agent, decisions, trustGiven, trustReceived } = detail.data
  const tint = agentColor(agent.id)
  const rank = report.data
    ? [...report.data.agents]
        .sort((a, b) => b.sharpe - a.sharpe)
        .findIndex((m) => m.agentId === agent.id) + 1 || null
    : null
  const nameOf = (aid: string) => agents.data?.find((a) => a.id === aid)?.name ?? aid
  const memoryById = new Map(memories.data?.map((m) => [m.id, m]))
  const messageById = new Map(forum.data?.messages.map((m) => [m.id, m]))
  const pageItems = decisions.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const pages = Math.ceil(decisions.length / PAGE_SIZE)

  return (
    <>
      <section
        className="relative mb-6 overflow-hidden rounded-3xl border glass p-6 sm:p-8"
        // The agent's own colour tints the panel from the top-left corner.
        style={{ backgroundImage: `radial-gradient(70% 90% at 0% 0%, ${tint}2e, transparent 60%)` }}
      >
        <Link
          to={`/experiments/${id}/live`}
          className="inline-flex items-center gap-1.5 rounded-full border bg-white/[0.04] px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" /> Canlı ekrana dön
        </Link>

        <div className="mt-6 grid gap-8 xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
          <div className="flex flex-col">
            <div className="flex items-center gap-4">
              <AgentAvatar id={agent.id} name={agent.name} className="size-16 text-lg" glow />
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Badge tone={isLlm ? 'info' : 'neutral'}>{agent.kind.toUpperCase()}</Badge>
                  {rank !== null && (
                    <span className="text-xs text-muted-foreground">
                      {rank}. sırada · {agents.data?.length ?? '–'} ajan
                    </span>
                  )}
                </div>
                <h1 className="mt-1.5 text-headline pb-1 text-4xl leading-none font-semibold tracking-[-0.04em] sm:text-5xl">
                  {agent.name}
                </h1>
              </div>
            </div>
            <p className="mt-3 max-w-md text-[15px] leading-relaxed text-muted-foreground">
              {agent.persona ?? `${agent.kind.toUpperCase()} ajanı`}
            </p>

            {stats && (
              <div className="mt-auto grid grid-cols-2 gap-x-6 gap-y-5 pt-8">
                <Stat size="lg" label="Portföy değeri" value={formatUsd(stats.equity)} />
                <Stat
                  size="lg"
                  label="Toplam getiri"
                  value={formatPct(stats.ret)}
                  tone={stats.ret >= 0 ? 'up' : 'down'}
                />
                <Stat size="lg" label="Sharpe (yıllık)" value={formatNum(stats.sharpe)} />
                <Stat size="lg" label="Maksimum düşüş" value={formatPct(-stats.mdd)} tone="down" />
              </div>
            )}
          </div>

          <div className="min-w-0 rounded-2xl border bg-black/25 p-4">
            <p className="mb-2 text-sm font-medium">Portföy geçmişi</p>
            <MultiLineChart lines={lines} height={260} label={`${agent.name} portföy değeri`} />
          </div>
        </div>
      </section>

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-4">
          {isLlm && (
            <Card>
              <CardHeader
                title="Kararlar ve gerekçeleri"
                description="Her karar, kullandığı anılar ve okuduğu forum mesajlarıyla izlenebilir (F6, NF4)."
              />
              <ul className="-mx-4 divide-y divide-border/60 border-y border-border/60">
                {pageItems.map((d) => (
                  <DecisionRow
                    key={d.id}
                    d={d}
                    expanded={open === d.id}
                    onToggle={() => setOpen(open === d.id ? null : d.id)}
                    memory={(mid) => memoryById.get(mid)?.lesson}
                    message={(fid) => {
                      const m = messageById.get(fid)
                      return m && `${nameOf(m.senderId)}: ${m.content}`
                    }}
                  />
                ))}
              </ul>
              <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
                <span className="num">
                  {decisions.length} karar · sayfa {page + 1}/{pages}
                </span>
                <div className="flex gap-1">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={page === 0}
                    onClick={() => setPage(page - 1)}
                  >
                    Önceki
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={page + 1 >= pages}
                    onClick={() => setPage(page + 1)}
                  >
                    Sonraki
                  </Button>
                </div>
              </div>
            </Card>
          )}
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader title="Güven skorları" description="Beta itibar: w = (a+1)/(a+b+2)" />
            {trustGiven.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                Bu koşulda forum yok veya ajan foruma katılmıyor.
              </p>
            ) : (
              <Table className="text-xs">
                <thead>
                  <tr>
                    <th>Ajan</th>
                    <th className="text-right">Verdiği</th>
                    <th className="text-right">Aldığı</th>
                  </tr>
                </thead>
                <tbody>
                  {trustGiven.map((t) => {
                    const back = trustReceived.find((r) => r.trusterId === t.trusteeId)
                    return (
                      <tr key={t.trusteeId}>
                        <td>
                          <span className="flex items-center gap-2">
                            <AgentAvatar
                              id={t.trusteeId}
                              name={nameOf(t.trusteeId)}
                              className="size-5 text-[8px]"
                            />
                            {nameOf(t.trusteeId)}
                          </span>
                        </td>
                        <td className="text-right num" title={`a=${t.confirmed}, b=${t.refuted}`}>
                          {formatNum(t.score)}
                        </td>
                        <td className="text-right num">{back ? formatNum(back.score) : '—'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </Table>
            )}
          </Card>

          {isLlm && (
            <Card>
              <CardHeader
                title="Hafıza"
                description={`${memories.data?.length ?? 0} kabul edilmiş ders`}
              />
              <div
                role="region"
                tabIndex={0}
                aria-label="Hafızadaki dersler"
                className="max-h-96 overflow-y-auto rounded-lg pr-1"
              >
                <ul className="space-y-2">
                  {memories.data?.slice(0, 20).map((m) => (
                    <li
                      key={m.id}
                      className="rounded-lg border border-border/70 bg-white/[0.03] p-2.5 text-xs leading-relaxed"
                    >
                      <div className="mb-1 flex items-center gap-2">
                        <RegimeBadge regime={m.regime} />
                        <span className="text-muted-foreground">{formatDate(m.day)}</span>
                        <span className="ml-auto num text-muted-foreground">
                          önem <span className="text-foreground">{formatNum(m.importance)}</span>
                        </span>
                      </div>
                      {m.lesson}
                    </li>
                  ))}
                </ul>
              </div>
            </Card>
          )}
        </div>
      </div>
    </>
  )
}

function DecisionRow({
  d,
  expanded,
  onToggle,
  memory,
  message,
}: {
  d: Decision
  expanded: boolean
  onToggle: () => void
  memory: (id: string) => string | undefined
  message: (id: string) => string | undefined
}) {
  const weights = Object.entries(d.targetWeights)
  return (
    <li className={cn(expanded && 'bg-white/[0.03]')}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors hover:bg-muted/30"
      >
        <ChevronRight
          aria-hidden
          className={cn(
            'mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform',
            expanded && 'rotate-90 text-primary',
          )}
        />
        <span className="w-22 shrink-0 pt-px num text-xs text-muted-foreground">
          {formatDate(d.day)}
        </span>
        <span className="flex-1 text-sm leading-relaxed">{d.rationale}</span>
        <span className="flex shrink-0 gap-1">
          {d.heldPosition && (
            <Badge tone="warn" className="gap-1">
              <ShieldAlert className="size-3" /> pozisyon korundu
            </Badge>
          )}
          {d.attempts > 1 && !d.heldPosition && (
            <Badge tone="neutral" className="gap-1">
              <RotateCw className="size-3" /> {d.attempts}. deneme
            </Badge>
          )}
        </span>
      </button>
      {expanded && (
        <div className="grid gap-4 px-4 pt-1 pb-4 text-xs sm:grid-cols-2 sm:pl-[8.5rem]">
          <div>
            <p className="mb-1.5 eyebrow">Karar (JSON)</p>
            <pre className="overflow-x-auto rounded-lg border bg-black/30 p-3 num text-[11px] leading-relaxed text-foreground/90">
              {JSON.stringify(
                {
                  allocations: weights.map(([asset, weight]) => ({ asset, weight })),
                  confidence: d.confidence,
                  regime: d.regime,
                  latency_ms: d.latencyMs,
                },
                null,
                2,
              )}
            </pre>
          </div>
          <div className="space-y-2">
            <p className="flex items-center gap-1.5 eyebrow">
              <BrainCircuit className="size-3" /> Kullanılan anılar ({d.memories.length})
            </p>
            {d.memories.length === 0 && (
              <p className="text-muted-foreground">Yok (hafızasız koşul veya henüz ders yok)</p>
            )}
            {d.memories.map((m) => (
              <p
                key={m.id}
                className="rounded-md border border-border/70 bg-white/[0.03] p-2 leading-relaxed"
              >
                <span className="num text-primary">{formatNum(m.score)}</span>{' '}
                {memory(m.id) ?? m.id}
              </p>
            ))}
            <p className="flex items-center gap-1.5 eyebrow">
              <MessageSquareText className="size-3" /> Okunan forum mesajları (
              {d.forumMessageIds.length})
            </p>
            {d.forumMessageIds.map((fid) => (
              <p
                key={fid}
                className="rounded-md border border-border/70 bg-white/[0.03] p-2 leading-relaxed"
              >
                {message(fid) ?? fid}
              </p>
            ))}
          </div>
        </div>
      )}
    </li>
  )
}
