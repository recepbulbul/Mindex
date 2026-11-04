import { agentColor } from '@/lib/identity'
import { cn } from '@/lib/utils'

const PLANETS = [
  { id: 'llm-momentum', ring: 0, angle: 20 },
  { id: 'llm-mean-reversion', ring: 1, angle: 140 },
  { id: 'llm-sentiment', ring: 2, angle: 250 },
  { id: 'llm-risk-averse', ring: 1, angle: 320 },
  { id: 'ppo', ring: 2, angle: 70 },
]
const RINGS = [110, 175, 240]

/**
 * Decorative hero object: agents orbiting a lit core. Only `transform` animates (compositor),
 * and the whole thing stops under prefers-reduced-motion.
 */
export function Orbit({ className }: { className?: string }) {
  return (
    <div aria-hidden className={cn('pointer-events-none relative aspect-square', className)}>
      <div className="absolute inset-[22%] rounded-full bg-[radial-gradient(circle_at_35%_30%,rgb(143_178_255/0.9),rgb(91_124_255/0.55)_35%,rgb(124_92_255/0.25)_60%,transparent_72%)] blur-md" />
      <svg
        viewBox="-260 -260 520 520"
        className="absolute inset-0 size-full motion-safe:animate-[orbit_80s_linear_infinite]"
      >
        {RINGS.map((r) => (
          <circle
            key={r}
            r={r}
            fill="none"
            stroke="rgb(255 255 255 / 0.09)"
            strokeDasharray="2 6"
          />
        ))}
        {PLANETS.map(({ id, ring, angle }) => {
          const r = RINGS[ring]!
          const x = r * Math.cos((angle * Math.PI) / 180)
          const y = r * Math.sin((angle * Math.PI) / 180)
          return (
            <g key={id}>
              <circle cx={x} cy={y} r="18" fill={agentColor(id)} opacity="0.18" />
              <circle cx={x} cy={y} r="7" fill={agentColor(id)} />
            </g>
          )
        })}
      </svg>
    </div>
  )
}
