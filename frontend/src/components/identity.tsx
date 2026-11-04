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
