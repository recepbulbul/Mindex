import type { Asset } from '@/api/types'
import { agentColor, agentInitials, ASSET_COLOR } from '@/lib/identity'
import { cn } from '@/lib/utils'

/** Gradient orb with initials; the same agent always gets the same colours. */
export function AgentAvatar({
  id,
  name,
  className,
  glow,
}: {
  id: string
  name: string
  className?: string
  glow?: boolean
}) {
  const c = agentColor(id)
  return (
    <span
      aria-hidden
      className={cn(
        'grid size-7 shrink-0 place-items-center rounded-full text-[10px] font-semibold tracking-tight text-foreground select-none',
        className,
      )}
      style={{
        backgroundColor: `${c}33`,
        boxShadow: `inset 0 0 0 1px ${c}99${glow ? `, 0 0 0 3px ${c}26` : ''}`,
      }}
    >
      {agentInitials(name)}
    </span>
  )
}

/** Small coin orb for a traded asset. */
export function AssetOrb({ asset, className }: { asset: Asset; className?: string }) {
  const c = ASSET_COLOR[asset]
  return (
    <span
      aria-hidden
      className={cn(
        'grid size-6 shrink-0 place-items-center rounded-full text-[9px] font-bold text-black/80 ring-2 ring-background',
        className,
      )}
      style={{ background: `radial-gradient(circle at 30% 30%, #fff8, ${c} 45%)` }}
    >
      {asset[0]}
    </span>
  )
}

/** Tiny inline trend line. */
export function Sparkline({
  values,
  className,
  color,
}: {
  values: number[]
  className?: string
  color?: string
}) {
  if (values.length < 2) return null
  const lo = Math.min(...values)
  const span = Math.max(...values) - lo || 1
  const pts = values.map((v, i) => [(i / (values.length - 1)) * 100, 28 - ((v - lo) / span) * 26])
  const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x!.toFixed(2)} ${y!.toFixed(2)}`).join(' ')
  const up = values.at(-1)! >= values[0]!
  const stroke = color ?? (up ? 'var(--up)' : 'var(--down)')
  return (
    <svg
      aria-hidden
      viewBox="0 0 100 30"
      preserveAspectRatio="none"
      className={cn('h-8 w-full overflow-visible', className)}
    >
      <path d={`${d} L100 30 L0 30Z`} fill={stroke} fillOpacity="0.12" />
      <path d={d} fill="none" stroke={stroke} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
