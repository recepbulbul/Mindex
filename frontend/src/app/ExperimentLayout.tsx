import { ChevronRight, Radio } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link, NavLink, Outlet, useOutletContext, useParams } from 'react-router'
import { useExperiment } from '@/api/queries'
import { CONDITION_LABELS } from '@/api/types'
import { StatusBadge } from '@/components/common'
import { Skeleton } from '@/components/ui/primitives'
import { cn } from '@/lib/utils'

const TABS = [
  ['live', 'Canlı borsa'],
  ['forum', 'Forum ve hafıza'],
  ['report', 'Rapor'],
] as const

/**
 * One header for every screen of an experiment: where you are, what it is, and tabs to move
 * between its views. The sidebar stays the same everywhere, so navigation never shifts.
 */
export function ExperimentLayout() {
  const { id = '' } = useParams()
  const { data } = useExperiment(id)
  const [actions, setActions] = useState<HTMLElement | null>(null)

  return (
    <>
      <header className="mb-5">
        <nav aria-label="Konum" className="flex items-center gap-1 text-xs text-muted-foreground">
          <Link to="/experiments" className="transition-colors hover:text-foreground">
            Deneyler
          </Link>
          <ChevronRight className="size-3.5" aria-hidden />
          <span className="truncate text-foreground">{data?.name ?? '…'}</span>
        </nav>

        <div className="mt-2 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
          <div className="min-w-0">
            {data ? (
              <h1 className="text-silver text-2xl leading-tight font-semibold tracking-[-0.025em] text-balance sm:text-[1.75rem]">
                {data.name}
              </h1>
            ) : (
              <Skeleton className="h-9 w-80" />
            )}
            {data && (
              <p className="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
                {CONDITION_LABELS[data.condition]} · {data.mode === 'live' ? 'Canlı' : 'Replay'} ·
                seed {data.seed} · {data.agentIds.length} ajan
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 print:hidden">
            {data?.mode === 'live' && data.status === 'running' && (
              <span className="inline-flex items-center gap-1.5 text-xs text-up">
                <Radio className="size-3.5 animate-pulse" /> Binance akışı (sahte)
              </span>
            )}
            {data && <StatusBadge status={data.status} />}
          </div>
        </div>

        {/* Actions sit beside the tabs but outside the navigation landmark. */}
        <div className="mt-4 flex items-center border-b print:hidden">
          <nav aria-label="Deney görünümleri" className="flex items-center gap-6">
            {TABS.map(([path, label]) => (
              <NavLink
                key={path}
                to={`/experiments/${id}/${path}`}
                className={({ isActive }) =>
                  cn(
                    '-mb-px border-b-2 pb-3 text-sm transition-colors',
                    isActive
                      ? 'border-foreground text-foreground'
                      : 'border-transparent text-muted-foreground hover:text-foreground',
                  )
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
          <div ref={setActions} className="-mt-2 ml-auto flex items-center gap-1" />
        </div>
      </header>
      <Outlet context={actions} />
    </>
  )
}

/** Puts a screen's own actions (export, print) next to the experiment status in the header. */
export function ExperimentActions({ children }: { children: ReactNode }) {
  const target = useOutletContext<HTMLElement | null>()
  return target ? createPortal(children, target) : null
}
