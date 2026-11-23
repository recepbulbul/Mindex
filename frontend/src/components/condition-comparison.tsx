import { CONDITION_LABELS, type ConditionDifference, type ConditionSummary } from '@/api/types'
import { Card, CardHeader, Table } from '@/components/ui/primitives'
import { USING_MOCKS } from '@/lib/env'
import { cn, formatNum, formatPct } from '@/lib/utils'

const CI_NOTE = USING_MOCKS
  ? 'Prototipte aralık = seed min–maks; gerçek sunucuda blok bootstrap %95 GA.'
  : 'Aralık: günler üzerinde dairesel blok bootstrap %95 GA.'

/** Mean Sharpe of LLM agents per condition with its interval, plus the other study metrics. */
export function ConditionComparison({
  conditions,
  className,
}: {
  conditions: ConditionSummary[]
  className?: string
}) {
  const c0 = conditions.find((c) => c.condition === 'C0')
  const runs = conditions.reduce((s, c) => s + c.runs, 0)
  const lo = Math.min(0, ...conditions.map((c) => c.sharpeCiLow))
  const hi = Math.max(...conditions.map((c) => c.sharpeCiHigh))
  const pos = (v: number) => `${((v - lo) / (hi - lo || 1)) * 100}%`

  return (
    <Card className={className}>
      <CardHeader
        title={`Koşul karşılaştırması (${conditions.length} koşul, ${runs} koşu)`}
        description={`LLM ajanlarının ortalaması. ${CI_NOTE}`}
      />
      <Table>
        <thead>
          <tr>
            <th>Koşul</th>
            <th className="text-right">Koşu</th>
            <th className="w-1/3">Sharpe (ort. ve %95 GA)</th>
            <th className="text-right">vs C0</th>
            <th className="text-right">MDD</th>
            <th className="text-right">Getiri</th>
            <th className="text-right">Sürü kor.</th>
            <th className="text-right">Ders tutarlılığı</th>
          </tr>
        </thead>
        <tbody>
          {conditions.map((c) => {
            // A ratio to a negative or zero C0 Sharpe has no meaning (the differences table has it).
            const vsC0 = c0 && c0.sharpeMean > 0 ? c.sharpeMean / c0.sharpeMean - 1 : null
            return (
              <tr key={c.condition}>
                <td className="whitespace-nowrap">{CONDITION_LABELS[c.condition]}</td>
                <td className="text-right num">{c.runs}</td>
                <td>
                  <div className="flex items-center gap-2">
                    <div
                      className="relative h-5 flex-1"
                      role="img"
                      aria-label={`Sharpe ${formatNum(c.sharpeMean)}, aralık ${formatNum(c.sharpeCiLow)}–${formatNum(c.sharpeCiHigh)}`}
                    >
                      <div
                        className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-primary/25"
                        style={{
                          left: pos(c.sharpeCiLow),
                          right: `calc(100% - ${pos(c.sharpeCiHigh)})`,
                        }}
                      />
                      <div
                        className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary ring-2 ring-card"
                        style={{ left: pos(c.sharpeMean) }}
                      />
                    </div>
                    <span className="w-10 text-right text-xs num">{formatNum(c.sharpeMean)}</span>
                  </div>
                </td>
                <td
                  className={cn('text-right num', vsC0 !== null && vsC0 >= 0.15 ? 'text-up' : '')}
                >
                  {c.condition === 'C0' || vsC0 === null ? '—' : formatPct(vsC0)}
                </td>
                <td className="text-right num">{formatPct(-c.maxDrawdown)}</td>
                <td className="text-right num">{formatPct(c.totalReturn)}</td>
                <td className="text-right num">{formatNum(c.herdCorrelation)}</td>
                <td className="text-right num">
                  {c.lessonConsistency === null ? '—' : formatPct(c.lessonConsistency)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </Table>
      <p className="mt-3 border-t pt-3 text-xs text-muted-foreground">
        Nicel hedef: C3 Sharpe ortalamasında C0'a göre ≥ %15 iyileşme.
      </p>
    </Card>
  )
}

const STEP: Record<string, string> = {
  'C1-C0': 'kişisel hafıza',
  'C1-C1_NO_REGIME': 'rejim bonusu',
  'C2-C1': 'forum',
  'C3-C2': 'güven ağırlığı',
  'C3-C0': 'hepsi birlikte',
}

/** Paired differences of the mean Sharpe; an interval that excludes 0 is called out. */
export function ConditionDifferences({ differences }: { differences: ConditionDifference[] }) {
  return (
    <Card>
      <CardHeader
        title="Koşul farkları"
        description="Sharpe farkı ve %95 GA; iki koşul aynı yeniden örneklenmiş günlerde karşılaştırılır. Aralık 0'ı içermiyorsa fark anlamlı sayılır."
      />
      <Table>
        <thead>
          <tr>
            <th>Fark</th>
            <th>Ölçtüğü</th>
            <th className="text-right">ΔSharpe</th>
            <th className="text-right">%95 GA</th>
            <th className="text-right">Sonuç</th>
          </tr>
        </thead>
        <tbody>
          {differences.map((d) => {
            const significant = d.ciLow > 0 || d.ciHigh < 0
            return (
              <tr key={`${d.condition}-${d.baseline}`}>
                <td className="whitespace-nowrap">
                  {CONDITION_LABELS[d.condition].split(' ·')[0]} −{' '}
                  {CONDITION_LABELS[d.baseline].split(' ·')[0]}
                </td>
                <td className="text-muted-foreground">
                  {STEP[`${d.condition}-${d.baseline}`] ?? ''}
                </td>
                <td
                  className={cn(
                    'text-right num',
                    significant && (d.sharpeDiff > 0 ? 'text-up' : 'text-down'),
                  )}
                >
                  {d.sharpeDiff > 0 ? '+' : ''}
                  {formatNum(d.sharpeDiff)}
                </td>
                <td className="text-right num whitespace-nowrap">
                  [{formatNum(d.ciLow)}, {formatNum(d.ciHigh)}]
                </td>
                <td className="text-right">{significant ? 'anlamlı' : 'belirsiz'}</td>
              </tr>
            )
          })}
        </tbody>
      </Table>
    </Card>
  )
}
