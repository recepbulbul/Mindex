import { useId } from 'react'
import type { ExperimentStatus, Regime } from '@/api/types'
import { REGIME_LABEL } from '@/lib/labels'
import { cn } from '@/lib/utils'
import { Badge } from './ui/primitives'

const STATUS: Record<
  ExperimentStatus,
  { label: string; tone: 'up' | 'down' | 'warn' | 'info' | 'neutral' }
> = {
  draft: { label: 'Taslak', tone: 'neutral' },
  queued: { label: 'Kuyrukta', tone: 'info' },
  running: { label: 'Çalışıyor', tone: 'up' },
  paused: { label: 'Duraklatıldı', tone: 'warn' },
  completed: { label: 'Tamamlandı', tone: 'info' },
  failed: { label: 'Hata', tone: 'down' },
}

export const StatusBadge = ({ status }: { status: ExperimentStatus }) => (
  <Badge
    tone={STATUS[status].tone}
    dot
    className={cn(status === 'running' && '[&>span:first-child]:animate-pulse')}
  >
    {STATUS[status].label}
  </Badge>
)

export const RegimeBadge = ({ regime }: { regime: Regime }) => (
  <Badge tone={regime === 'bull' ? 'up' : regime === 'bear' ? 'down' : 'neutral'}>
    {REGIME_LABEL[regime]}
  </Badge>
)

/** The Mindex mark: agents (nodes) climbing a shared equity curve, on the brand gradient. */
export function BrandMark({ className }: { className?: string }) {
  const id = useId()
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cn('size-8', className)}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--brand-from)" />
          <stop offset="1" stopColor="var(--brand-to)" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill={`url(#${id})`} />

      <path
        d="M7 22.5 13 15l5 4 7-9.5"
        fill="none"
        stroke="var(--primary-foreground)"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="7" cy="22.5" r="2.1" fill="var(--primary-foreground)" />
      <circle cx="13" cy="15" r="2.1" fill="var(--primary-foreground)" />
      <circle cx="18" cy="19" r="2.1" fill="var(--primary-foreground)" />
      <circle cx="25" cy="9.5" r="2.8" fill="var(--primary-foreground)" />
    </svg>
  )
}

export function PageTitle({
  title,
  subtitle,
  eyebrow,
  actions,
}: {
  title: string
  subtitle?: string
  eyebrow?: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div className="min-w-0">
        {eyebrow && (
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border bg-white/[0.04] px-2.5 py-1 text-[11px] font-medium text-primary [&_a]:text-muted-foreground [&_a:hover]:text-foreground [&_svg]:size-3.5">
            {eyebrow}
          </div>
        )}
        <h1 className="text-headline pb-1 text-[2.5rem] leading-[1.05] font-semibold tracking-[-0.04em] text-balance sm:text-[3.25rem]">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-pretty text-muted-foreground">
            {subtitle}
          </p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2 print:hidden">{actions}</div>}
    </div>
  )
}
