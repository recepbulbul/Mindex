import {
  BrainCircuit,
  CheckCircle2,
  MessagesSquare,
  Search,
  ShieldAlert,
  XCircle,
} from 'lucide-react'
import { useDeferredValue, useMemo, useState } from 'react'
import { useParams } from 'react-router'
import { useAgents, useForum, useMemories, type MemoryFilter } from '@/api/queries'
import type { Regime, TrustScore } from '@/api/types'
import { MultiLineChart } from '@/components/charts/charts'
import { PageTitle, RegimeBadge } from '@/components/common'
import { AgentAvatar } from '@/components/identity'
import { segmentClass, segmentedClass } from '@/components/ui/button-variants'
import { REGIME_LABEL } from '@/lib/labels'
import { rovingKeyDown } from '@/lib/roving'
import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Input,
  Select,
  Skeleton,
} from '@/components/ui/primitives'
import { agentColor } from '@/lib/identity'
import { cn, formatDate, formatNum, formatPct } from '@/lib/utils'

type Tab = 'forum' | 'memory'

export default function ForumPage() {
  const { id = '' } = useParams()
  const [tab, setTab] = useState<Tab>('forum')

  return (
    <>
      <PageTitle
        eyebrow={
          <>
            <MessagesSquare className="size-3.5" /> Ortak öğrenme
          </>
        }
        title="Forum ve hafıza"
        subtitle="Ajanlar arası mesajlar, güven ağırlıkları ve rejim etiketli dersler (F7)."
      />
      <div
        role="tablist"
        aria-label="Görünüm"
        className={cn(segmentedClass, 'mb-5')}
        onKeyDown={rovingKeyDown}
        tabIndex={-1}
      >
        {(
          [
            ['forum', 'Forum'],
            ['memory', 'Hafıza tarayıcı'],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            tabIndex={tab === key ? 0 : -1}
            onClick={() => setTab(key)}
            className={cn(segmentClass(tab === key), 'px-3.5 py-1.5 text-[13px]')}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === 'forum' ? <ForumView id={id} /> : <MemoryView id={id} />}
    </>
  )
}

function ForumView({ id }: { id: string }) {
  const forum = useForum(id)
  const agents = useAgents()
  const [sender, setSender] = useState('')
  const [onlyFlagged, setOnlyFlagged] = useState(false)
  const nameOf = (aid: string) => agents.data?.find((a) => a.id === aid)?.name ?? aid

  const lines = useMemo(() => {
    const history = forum.data?.trustHistory ?? []
    const ids = [...new Set(history.map((h) => h.trusteeId))]
    return ids.map((tid) => ({
      id: tid,
      name: tid.replace('llm-', ''),
      color: agentColor(tid),
      points: history
        .filter((h) => h.trusteeId === tid)
        .map((h) => ({ time: h.day, value: h.score })),
    }))
  }, [forum.data])

  if (forum.error) return <ErrorState error={forum.error} onRetry={() => void forum.refetch()} />
  if (!forum.data) return <Skeleton className="h-96" />
  if (forum.data.messages.length === 0)
    return (
      <Card>
        <EmptyState icon={<MessagesSquare />} title="Forum kapalı">
          Bu deney koşulunda (C0/C1) forum kapalı.
        </EmptyState>
      </Card>
    )

  const { messages, trust } = forum.data
  const senders = [...new Set(messages.map((m) => m.senderId))]
  const shown = messages
    .filter((m) => (!sender || m.senderId === sender) && (!onlyFlagged || m.flagged))
    .slice(0, 100)
  const avgTrust = (sid: string) => {
    const xs = trust.filter((t) => t.trusteeId === sid)
    return xs.length ? xs.reduce((s, t) => s + t.score, 0) / xs.length : null
  }

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
      <Card>
        <CardHeader
          title="Mesaj akışı"
          description="Mesajlar güvenilmeyen veri olarak işlenir; talimat içerenler filtrelenir (OWASP LLM01)."
          action={
            <div className="flex items-center gap-2">
              <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
                <input
                  type="checkbox"
                  checked={onlyFlagged}
                  onChange={(e) => setOnlyFlagged(e.target.checked)}
                />
                Yalnızca filtrelenenler
              </label>
              <Select
                aria-label="Gönderen"
                value={sender}
                onChange={(e) => setSender(e.target.value)}
                className="h-8 w-44 text-xs"
              >
                <option value="">Tüm ajanlar</option>
                {senders.map((s) => (
                  <option key={s} value={s}>
                    {nameOf(s)}
                  </option>
                ))}
              </Select>
            </div>
          }
        />
        <div
          role="region"
          tabIndex={0}
          aria-label="Forum mesajları"
          className="-mr-2 max-h-[680px] overflow-y-auto rounded-lg pr-2"
        >
          <ul className="space-y-2">
            {shown.map((m) => {
              const w = avgTrust(m.senderId)
              return (
                <li
                  key={m.id}
                  className={cn(
                    'rounded-lg border border-border/70 bg-white/[0.03] p-3 text-sm transition-colors hover:border-border-strong',
                    m.flagged &&
                      'border-destructive/40 bg-destructive/[0.06] hover:border-destructive/60',
                  )}
                >
                  <div className="mb-1.5 flex flex-wrap items-center gap-2 text-xs">
                    <AgentAvatar
                      id={m.senderId}
                      name={nameOf(m.senderId)}
                      className="size-6 text-[9px]"
                    />
                    <span className="font-medium">{nameOf(m.senderId)}</span>
                    {w !== null && (
                      <span className="num text-muted-foreground">güven {formatNum(w)}</span>
                    )}
                    <Badge
                      tone={
                        m.stance === 'bullish' ? 'up' : m.stance === 'bearish' ? 'down' : 'neutral'
                      }
                    >
                      {m.asset} ·{' '}
                      {m.stance === 'bullish'
                        ? 'yükseliş'
                        : m.stance === 'bearish'
                          ? 'düşüş'
                          : 'nötr'}
                    </Badge>
                    <span className="ml-auto num text-muted-foreground">{formatDate(m.day)}</span>
                  </div>
                  <p className={cn('leading-relaxed', m.flagged && 'line-through opacity-70')}>
                    {m.content}
                  </p>
                  <div className="mt-2 text-xs">
                    {m.flagged ? (
                      <span className="flex items-center gap-1 text-destructive">
                        <ShieldAlert className="size-3" /> Prompt injection şüphesi · ajanlara
                        iletilmedi
                      </span>
                    ) : m.verified === true ? (
                      <span className="flex items-center gap-1 text-up">
                        <CheckCircle2 className="size-3" /> 5 gün sonra doğrulandı (a+1)
                      </span>
                    ) : m.verified === false ? (
                      <span className="flex items-center gap-1 text-down">
                        <XCircle className="size-3" /> Çürüdü (b+1)
                      </span>
                    ) : (
                      <span className="text-muted-foreground">Değerlendirme bekleniyor</span>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      </Card>

      <div className="space-y-4">
        <Card>
          <CardHeader
            title="Güven matrisi"
            description="Satır güvenir → sütun güvenilen; w = (a+1)/(a+b+2)"
          />
          <TrustMatrix trust={trust} label={(x) => x.replace('llm-', '')} />
        </Card>
        <Card>
          <CardHeader
            title="Güvenin zaman içindeki değişimi"
            description="Diğer ajanların ortalama güveni"
          />
          <MultiLineChart
            lines={lines}
            height={240}
            label="Ajanlara duyulan ortalama güvenin zaman serisi"
          />
        </Card>
      </div>
    </div>
  )
}

function TrustMatrix({ trust, label }: { trust: TrustScore[]; label: (id: string) => string }) {
  const ids = [...new Set(trust.flatMap((t) => [t.trusterId, t.trusteeId]))]
  const cell = (a: string, b: string) => trust.find((t) => t.trusterId === a && t.trusteeId === b)
  return (
    <table className="w-full table-fixed border-separate border-spacing-0.5 text-center text-xs">
      <thead>
        <tr>
          <th scope="col">
            <span className="sr-only">Güvenen ajan</span>
          </th>
          {ids.map((b) => (
            <th key={b} scope="col" className="truncate pb-1 font-medium text-muted-foreground">
              {label(b)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {ids.map((a) => (
          <tr key={a}>
            <th scope="row" className="truncate pr-1 text-left font-medium text-muted-foreground">
              {label(a)}
            </th>
            {ids.map((b) => {
              const c = cell(a, b)
              if (!c)
                return (
                  <td key={b} className="text-muted-foreground">
                    —
                  </td>
                )
              // Diverging scale around the neutral prior 0.5.
              const alpha = Math.min(1, Math.abs(c.score - 0.5) * 4)
              const color = `color-mix(in oklch, var(${c.score >= 0.5 ? '--up' : '--down'}) ${Math.round(alpha * 55)}%, transparent)`
              return (
                <td key={b}>
                  <div
                    className="rounded-md py-2 num text-[11px]"
                    style={{ background: color }}
                    title={`a=${c.confirmed}, b=${c.refuted}`}
                  >
                    {formatNum(c.score)}
                  </div>
                </td>
              )
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function MemoryView({ id }: { id: string }) {
  const agents = useAgents()
  const [regime, setRegime] = useState<Regime | ''>('')
  const [agent, setAgent] = useState('')
  const [q, setQ] = useState('')
  const deferredQ = useDeferredValue(q)
  const filter: MemoryFilter = { regime, agent, q: deferredQ }
  const memories = useMemories(id, filter)
  const llmAgents = agents.data?.filter((a) => a.kind === 'llm') ?? []

  return (
    <Card>
      <div className="mb-4 flex flex-wrap gap-2">
        <div className="relative min-w-60 flex-1">
          <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
          <Input
            aria-label="Derslerde ara"
            placeholder="Derslerde ara (örn. zarar-kes, BTC)…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="pl-8"
          />
        </div>
        <Select
          aria-label="Rejim"
          value={regime}
          onChange={(e) => setRegime(e.target.value as Regime | '')}
          className="w-40"
        >
          <option value="">Tüm rejimler</option>
          {(Object.keys(REGIME_LABEL) as Regime[]).map((r) => (
            <option key={r} value={r}>
              {REGIME_LABEL[r]}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Ajan"
          value={agent}
          onChange={(e) => setAgent(e.target.value)}
          className="w-52"
        >
          <option value="">Tüm LLM ajanları</option>
          {llmAgents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </Select>
      </div>

      {memories.error ? (
        <ErrorState error={memories.error} />
      ) : !memories.data ? (
        <Skeleton className="h-64" />
      ) : memories.data.length === 0 ? (
        <EmptyState icon={<BrainCircuit />} title="Eşleşen ders yok">
          Filtreleri gevşetin. C0 koşulunda hafıza kapalıdır.
        </EmptyState>
      ) : (
        <>
          <p className="mb-3 eyebrow" aria-live="polite">
            {memories.data.length} ders
          </p>
          <ul className="grid gap-3 md:grid-cols-2">
            {memories.data.slice(0, 60).map((m) => (
              <li
                key={m.id}
                className="flex flex-col rounded-lg border border-border/70 bg-white/[0.03] p-3.5 text-sm transition-colors hover:border-border-strong"
              >
                <div className="mb-2 flex items-center gap-2 text-xs">
                  <RegimeBadge regime={m.regime} />
                  <span>{agents.data?.find((a) => a.id === m.agentId)?.name}</span>
                  <span className="ml-auto text-muted-foreground">{formatDate(m.day)}</span>
                </div>
                <p className="flex-1 leading-relaxed">{m.lesson}</p>
                <dl className="mt-3 grid grid-cols-4 gap-px overflow-hidden rounded-md border bg-border text-center text-xs [&>div]:bg-card [&>div]:px-1 [&>div]:py-1.5">
                  {(
                    [
                      ['Gerçekleşen', m.counterfactual.actual],
                      ['Girmemek', m.counterfactual.skip],
                      ['Yarım', m.counterfactual.half],
                      ['Zarar-kes', m.counterfactual.stopLoss],
                    ] as const
                  ).map(([k, v]) => (
                    <div key={k}>
                      <dt className="text-[10px] text-muted-foreground">{k}</dt>
                      <dd
                        className={cn('mt-0.5 num', v > 0 ? 'text-up' : v < 0 ? 'text-down' : '')}
                      >
                        {formatPct(v)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  )
}
