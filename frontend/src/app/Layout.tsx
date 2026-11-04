import { FlaskConical, Plus, type LucideIcon } from 'lucide-react'
import { Link, NavLink, Outlet } from 'react-router'
import { useExperiments } from '@/api/queries'
import { useAuth } from '@/auth/AuthContext'
import { BrandMark } from '@/components/common'
import { cn } from '@/lib/utils'

const navClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    'group relative flex shrink-0 items-center gap-2.5 rounded-xl px-3 py-2 text-[13px] whitespace-nowrap transition-all [&_svg]:size-4 [&_svg]:shrink-0',
    isActive
      ? 'bg-white/[0.07] text-foreground shadow-[inset_0_1px_0_oklch(1_0_0/0.08)] [&_svg]:text-primary before:absolute before:inset-y-2 before:-left-3 before:w-0.5 before:rounded-full before:bg-brand'
      : 'text-muted-foreground hover:bg-white/[0.04] hover:text-foreground',
  )

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  end?: boolean
}

function NavItems({ items }: { items: NavItem[] }) {
  return items.map(({ to, label, icon: Icon, end }) => (
    <NavLink key={to} to={to} end={end} className={navClass}>
      <Icon /> {label}
    </NavLink>
  ))
}

/** Started experiments, newest first: one click back into a running race from anywhere. */
function ExperimentShortcuts() {
  const { data } = useExperiments()
  const started = data?.filter((e) => e.status !== 'draft').slice(0, 5)
  if (!started?.length) return null
  return (
    <div className="space-y-0.5">
      <p className="mb-2 px-2.5 eyebrow">Deneyler</p>
      {started.map((e) => (
        <NavLink
          key={e.id}
          to={`/experiments/${e.id}`}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-2.5 rounded-xl px-3 py-2 text-[13px] transition-colors',
              isActive
                ? 'bg-white/[0.07] text-foreground'
                : 'text-muted-foreground hover:bg-white/[0.04] hover:text-foreground',
            )
          }
        >
          <span
            aria-hidden
            className={cn(
              'size-1.5 shrink-0 rounded-full',
              e.status === 'running' ? 'animate-pulse bg-up' : 'bg-muted-foreground/50',
            )}
          />
          <span className="truncate">{e.name}</span>
        </NavLink>
      ))}
    </div>
  )
}

export function Layout() {
  const { user } = useAuth()
  const isResearcher = user?.role === 'researcher'

  const workspace: NavItem[] = [
    { to: '/experiments', label: 'Tüm deneyler', icon: FlaskConical, end: true },
    ...(isResearcher ? [{ to: '/experiments/new', label: 'Yeni deney', icon: Plus }] : []),
  ]
  const roleLabel = isResearcher ? 'Araştırmacı' : 'İzleyici'

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[240px_minmax(0,1fr)]">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        İçeriğe geç
      </a>

      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh flex-col border-r bg-surface lg:flex print:hidden">
        <Link to="/experiments" className="flex items-center gap-2.5 px-4 pt-5 pb-6">
          <BrandMark className="size-7" />
          <span className="leading-none">
            <span className="block text-[15px] font-semibold tracking-tight">Mindex</span>
            <span className="mt-1 block eyebrow text-[10px]">Ajan arenası</span>
          </span>
        </Link>

        <nav aria-label="Ana menü" className="flex-1 space-y-6 overflow-y-auto px-3">
          <div className="space-y-0.5">
            <p className="mb-2 px-2.5 eyebrow">Çalışma alanı</p>
            <NavItems items={workspace} />
          </div>
          <ExperimentShortcuts />
        </nav>

        <div className="space-y-2 border-t p-3">
          <div className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[11px] text-muted-foreground">
            <span className="size-1.5 rounded-full bg-warn" aria-hidden />
            Sahte API (MSW) · gerçek para yok
          </div>
          {/* The account is a row like any other link, not a boxed widget. */}
          <div>
            <NavLink
              to="/account"
              className={(state) => cn(navClass(state), 'min-w-0 flex-1 py-1.5')}
            >
              <span
                aria-hidden
                className="grid size-7 shrink-0 place-items-center rounded-full bg-[linear-gradient(180deg,#f8fafd,#aab4c8)] text-[11px] font-semibold text-primary-foreground uppercase"
              >
                {user?.email.slice(0, 2)}
              </span>
              <span className="min-w-0 leading-tight">
                <span className="block truncate text-xs text-foreground">{user?.email}</span>
                <span className="block text-[11px] text-muted-foreground">{roleLabel}</span>
              </span>
            </NavLink>
          </div>
        </div>
      </aside>

      <div className="min-w-0">
        {/* Mobile / tablet top bar */}
        <header className="sticky top-0 z-20 border-b bg-surface backdrop-blur lg:hidden print:hidden">
          <div className="flex h-14 items-center gap-3 px-4">
            <Link to="/experiments" className="flex items-center gap-2 font-semibold">
              <BrandMark className="size-7" /> Mindex
            </Link>
            <span className="ml-auto text-xs text-muted-foreground">{roleLabel}</span>
            <Link
              to="/account"
              aria-label="Hesap"
              className="grid size-8 place-items-center rounded-full bg-[linear-gradient(180deg,#f8fafd,#aab4c8)] text-[11px] font-semibold text-primary-foreground uppercase"
            >
              {user?.email.slice(0, 2)}
            </Link>
          </div>
          <nav
            aria-label="Ana menü (mobil)"
            className="flex gap-1 overflow-x-auto px-3 pb-2 [&_a]:before:hidden"
          >
            <NavItems items={workspace} />
          </nav>
        </header>

        <main id="main" className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8 lg:py-9">
          <div className="animate-rise">
            <Outlet />
          </div>
        </main>
        <footer className="mx-auto max-w-[1440px] px-4 pb-8 text-xs text-muted-foreground sm:px-6 lg:px-8 print:hidden">
          Prototip · tüm veriler sahte (MSW) · gerçek para kullanılmaz · Grafikler{' '}
          <a
            href="https://www.tradingview.com/"
            target="_blank"
            rel="noreferrer"
            className="underline-offset-4 hover:text-foreground hover:underline"
          >
            TradingView Lightweight Charts
          </a>
        </footer>
      </div>
    </div>
  )
}
