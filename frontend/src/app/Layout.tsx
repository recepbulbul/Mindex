import {
  Activity,
  BarChart3,
  FlaskConical,
  LogOut,
  MessagesSquare,
  Plus,
  type LucideIcon,
} from 'lucide-react'
import { Link, NavLink, Outlet, useParams } from 'react-router'
import { useExperiment } from '@/api/queries'
import { useAuth } from '@/auth/AuthContext'
import { BrandMark, StatusBadge } from '@/components/common'
import { Button } from '@/components/ui/button'
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

function ExperimentContext({ id }: { id: string }) {
  const { data } = useExperiment(id)
  return (
    <div className="mb-2 rounded-xl border bg-white/[0.03] px-3 py-2.5">
      <p className="eyebrow">Açık deney</p>
      <p className="mt-1 line-clamp-2 text-[13px] leading-snug font-medium">
        {data?.name ?? 'Yükleniyor…'}
      </p>
      {data && (
        <div className="mt-1.5 flex items-center gap-1.5">
          <StatusBadge status={data.status} />
          <span className="num text-[11px] text-muted-foreground">seed {data.seed}</span>
        </div>
      )}
    </div>
  )
}

export function Layout() {
  const { user, logout } = useAuth()
  const { id } = useParams()
  const isResearcher = user?.role === 'researcher'

  const workspace: NavItem[] = [
    { to: '/experiments', label: 'Deneyler', icon: FlaskConical, end: true },
    ...(isResearcher ? [{ to: '/experiments/new', label: 'Yeni deney', icon: Plus }] : []),
  ]
  const experiment: NavItem[] = id
    ? [
        { to: `/experiments/${id}/live`, label: 'Canlı borsa', icon: Activity },
        { to: `/experiments/${id}/forum`, label: 'Forum & hafıza', icon: MessagesSquare },
        { to: `/experiments/${id}/report`, label: 'Rapor', icon: BarChart3 },
      ]
    : []
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
          {id && (
            <div className="space-y-0.5">
              <p className="mb-2 px-2.5 eyebrow">Deney</p>
              <ExperimentContext id={id} />
              <NavItems items={experiment} />
            </div>
          )}
        </nav>

        <div className="space-y-3 border-t p-3">
          <div className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[11px] text-muted-foreground">
            <span className="size-1.5 rounded-full bg-warn" aria-hidden />
            Sahte API (MSW) · gerçek para yok
          </div>
          <div className="flex items-center gap-2.5 rounded-xl border bg-white/[0.03] px-2.5 py-2">
            <span
              aria-hidden
              className="grid size-8 shrink-0 place-items-center rounded-full bg-primary text-xs font-semibold text-primary-foreground uppercase ring-1 ring-white/20"
            >
              {user?.email.slice(0, 2)}
            </span>
            <span className="min-w-0 flex-1 leading-tight">
              <span className="block truncate text-xs font-medium">{user?.email}</span>
              <span className="block text-[11px] text-muted-foreground">{roleLabel}</span>
            </span>
            <Button variant="ghost" size="icon" onClick={logout} aria-label="Çıkış yap">
              <LogOut />
            </Button>
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
            <Button variant="ghost" size="icon" onClick={logout} aria-label="Çıkış yap">
              <LogOut />
            </Button>
          </div>
          <nav
            aria-label="Ana menü (mobil)"
            className="flex gap-1 overflow-x-auto px-3 pb-2 [&_a]:before:hidden"
          >
            <NavItems items={[...workspace, ...experiment]} />
          </nav>
        </header>

        <main id="main" className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8 lg:py-9">
          <div className="animate-rise">
            <Outlet />
          </div>
        </main>
        <footer className="mx-auto max-w-[1440px] px-4 pb-8 text-xs text-muted-foreground sm:px-6 lg:px-8 print:hidden">
          Prototip · tüm veriler sahte (MSW) · gerçek para kullanılmaz
        </footer>
      </div>
    </div>
  )
}
