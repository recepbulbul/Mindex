import { FAILURE_KINDS, FAILURE_LABELS, type FailureCounts, type Report } from '@/api/types'

/** "geçersiz JSON 3 · şema ihlali 0 · portföy kuralı 1": failed decision attempts by kind. */
export function formatFailures(counts: FailureCounts) {
  return FAILURE_KINDS.map((k) => `${FAILURE_LABELS[k]} ${counts[k] ?? 0}`).join(' · ')
}

export function totalFailures(counts: FailureCounts) {
  return FAILURE_KINDS.reduce((s, k) => s + (counts[k] ?? 0), 0)
}

export function reportToCsv(report: Report, nameOf: (id: string) => string) {
  const rows = [
    ['agent', 'total_return', 'sharpe', 'max_drawdown', 'trades'],
    ...report.agents.map((a) => [
      nameOf(a.agentId),
      a.totalReturn,
      a.sharpe,
      a.maxDrawdown,
      a.trades,
    ]),
  ]
  return rows
    .map((r) =>
      r
        .map((v) => (typeof v === 'number' ? v.toFixed(6) : `"${v.replaceAll('"', '""')}"`))
        .join(','),
    )
    .join('\n')
}
