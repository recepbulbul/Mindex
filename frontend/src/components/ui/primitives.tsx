import { cva, type VariantProps } from 'class-variance-authority'
import { AlertTriangle } from 'lucide-react'
import type { ComponentProps, PointerEvent, ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** Moves the card's spotlight to the pointer (see `.spotlight` in index.css). */
function trackSpotlight(e: PointerEvent<HTMLElement>) {
  const r = e.currentTarget.getBoundingClientRect()
  e.currentTarget.style.setProperty('--mx', `${e.clientX - r.left}px`)
  e.currentTarget.style.setProperty('--my', `${e.clientY - r.top}px`)
}

export function Card({ className, ...props }: ComponentProps<'section'>) {
  return (
    <section
      onPointerMove={trackSpotlight}
      className={cn(
        'rounded-2xl border glass p-6 print:break-inside-avoid print:shadow-none print:backdrop-blur-none',
        className,
      )}
      {...props}
    />
  )
}

export function CardHeader({
  title,
  description,
  action,
}: {
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
}) {
  return (
    <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        {description && (
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{description}</p>
        )}
      </div>
      {action}
    </header>
  )
}

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] leading-4 font-medium whitespace-nowrap ring-1 ring-inset',
  {
    variants: {
      tone: {
        neutral: 'bg-white/[0.05] text-muted-foreground ring-border-strong',
        up: 'bg-up/10 text-up ring-up/30',
        down: 'bg-down/10 text-down ring-down/30',
        warn: 'bg-warn/10 text-warn ring-warn/30',
        info: 'bg-info/10 text-info ring-info/30',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
)

export function Badge({
  className,
  tone,
  dot,
  children,
  ...props
}: ComponentProps<'span'> & VariantProps<typeof badgeVariants> & { dot?: boolean }) {
  return (
    <span className={cn(badgeVariants({ tone }), className)} {...props}>
      {dot && <span aria-hidden className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  )
}

const control =
  'h-9 w-full rounded-xl border border-border-strong bg-black/25 px-3 text-sm shadow-[inset_0_1px_2px_oklch(0_0_0/0.3)] transition-colors placeholder:text-muted-foreground/70 hover:border-white/25 focus-visible:border-primary/80 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-primary/20 disabled:opacity-45 aria-invalid:border-destructive aria-invalid:ring-destructive/20'

export function Input({ className, ...props }: ComponentProps<'input'>) {
  return <input className={cn(control, className)} {...props} />
}

export function Select({ className, ...props }: ComponentProps<'select'>) {
  // The open list is drawn by the OS: without explicit colours Windows shows it light on dark.
  return (
    <select
      className={cn(control, 'pr-8 [&_option]:bg-elevated [&_option]:text-foreground', className)}
      {...props}
    />
  )
}

export function Field({
  label,
  htmlFor,
  error,
  hint,
  children,
}: {
  label: string
  htmlFor: string
  error?: string
  hint?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-xs font-medium text-foreground/90">
        {label}
      </label>
      {children}
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : (
        hint && <p className="text-xs text-muted-foreground">{hint}</p>
      )}
    </div>
  )
}

export function Table({ className, ...props }: ComponentProps<'table'>) {
  return (
    <div className="-mx-5 overflow-x-auto px-5">
      <table
        className={cn(
          'w-full border-collapse text-sm',
          '[&_th]:border-b [&_th]:px-2.5 [&_th]:pb-3 [&_th]:text-left [&_th]:eyebrow [&_th]:font-normal',
          '[&_tbody_tr]:border-b [&_tbody_tr]:border-border/50 [&_tbody_tr:last-child]:border-0 [&_td]:px-2.5 [&_td]:py-3',
          '[&_tbody_tr]:transition-colors [&_tbody_tr:hover]:bg-white/[0.03]',
          className,
        )}
        {...props}
      />
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn(
        'animate-shimmer rounded-xl bg-[linear-gradient(90deg,var(--card)_0%,var(--muted)_40%,var(--card)_80%)] bg-[length:200%_100%]',
        className,
      )}
    />
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : 'Beklenmeyen bir hata oluştu.'
  return (
    <div
      role="alert"
      className="flex gap-3 rounded-xl border border-destructive/35 bg-destructive/[0.07] p-4 text-sm"
    >
      <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0 text-destructive" />
      <div>
        <p className="font-medium">Veri yüklenemedi</p>
        <p className="mt-1 text-muted-foreground">{message}</p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 text-xs font-medium text-foreground underline decoration-border-strong underline-offset-4 hover:decoration-foreground"
          >
            Tekrar dene
          </button>
        )}
      </div>
    </div>
  )
}

export function Stat({
  label,
  value,
  tone,
  hint,
  size = 'md',
}: {
  label: string
  value: ReactNode
  tone?: 'up' | 'down'
  hint?: ReactNode
  /** `lg` for hero panels. */
  size?: 'md' | 'lg'
}) {
  return (
    <div className="min-w-0">
      <p className="eyebrow">{label}</p>
      <p
        className={cn(
          'truncate font-medium num tracking-tight',
          size === 'lg' ? 'mt-1 text-3xl' : 'mt-2 text-2xl',
          tone === 'up' ? 'text-up' : tone === 'down' ? 'text-down' : 'text-silver',
        )}
      >
        {value}
      </p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

/** A row of KPI tiles separated by hairlines. */
export function StatGrid({ className, ...props }: ComponentProps<'section'>) {
  return (
    <section
      className={cn(
        'grid overflow-hidden border-y [&>*]:-mt-px [&>*]:-ml-px [&>*]:border-t [&>*]:border-l [&>*]:py-5 [&>*]:pl-5',
        className,
      )}
      {...props}
    />
  )
}

export function EmptyState({
  icon,
  title,
  children,
}: {
  icon?: ReactNode
  title: string
  children?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      {icon && (
        <div className="mb-1 grid size-11 place-items-center rounded-2xl border bg-white/[0.04] text-primary shadow-[inset_0_1px_0_oklch(1_0_0/0.08)] [&_svg]:size-5">
          {icon}
        </div>
      )}
      <p className="text-sm font-medium">{title}</p>
      {children && <div className="max-w-sm text-sm text-muted-foreground">{children}</div>}
    </div>
  )
}
