import { Copy, KeyRound, LogOut, ShieldCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { useAuth } from '@/auth/AuthContext'
import { PageTitle, UserAvatar } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/primitives'

/** One labelled row of the account sheet: label on the left, value and action on the right. */
function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="grid gap-2 border-b py-5 sm:grid-cols-[220px_minmax(0,1fr)] sm:gap-8">
      <div>
        <p className="text-sm font-medium">{label}</p>
        {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-3 text-sm">{children}</div>
    </div>
  )
}

// Prototype values only: there is no real key or session behind this screen.
const MOCK_MCP_KEY = 'mdx_test_••••••••••••7f2c'

export default function AccountPage() {
  const { user, logout } = useAuth()
  if (!user) return null
  const isResearcher = user.role === 'researcher'

  return (
    <div className="max-w-3xl">
      <PageTitle title="Hesap" subtitle="Profiliniz, yetkiniz ve dış ajan bağlantısı." />

      <section className="flex items-center gap-5 border-y py-6">
        <UserAvatar email={user.email} className="size-16 text-xl shadow-[inset_0_1px_0_white]" />
        <div className="min-w-0">
          <p className="truncate text-silver text-xl font-semibold tracking-tight">{user.email}</p>
          <p className="mt-1 flex items-center gap-1.5 text-sm text-muted-foreground">
            <ShieldCheck className="size-4" />
            {isResearcher ? 'Araştırmacı · deney tanımlar ve başlatır' : 'İzleyici · yalnızca okur'}
          </p>
        </div>
      </section>

      <Row label="Rol" hint="Yetkiyi yönetici atar">
        <Badge tone={isResearcher ? 'info' : 'neutral'}>
          {isResearcher ? 'Araştırmacı' : 'İzleyici'}
        </Badge>
      </Row>
      <Row label="Oturum" hint="JWT, tarayıcı oturumu kapanınca biter">
        <span className="text-muted-foreground">Bu tarayıcıda açık</span>
      </Row>
      {isResearcher && (
        <Row label="MCP erişim anahtarı" hint="Dış ajanların arenaya bağlanması için (P7)">
          <span className="flex items-center gap-2 rounded-lg border bg-black/30 px-3 py-1.5 text-xs num">
            <KeyRound className="size-3.5 text-muted-foreground" />
            {MOCK_MCP_KEY}
          </span>
          <Badge tone="warn">Sahte</Badge>
          <Button size="sm" variant="ghost" className="ml-auto" disabled>
            <Copy /> Kopyala
          </Button>
        </Row>
      )}
      <Row label="Veri" hint="Prototip">
        <span className="text-muted-foreground">
          Tüm veriler sahte (MSW). Gerçek para ya da borsa hesabı kullanılmaz.
        </span>
      </Row>

      <Button variant="outline" className="mt-8" onClick={logout}>
        <LogOut /> Oturumu kapat
      </Button>
    </div>
  )
}
