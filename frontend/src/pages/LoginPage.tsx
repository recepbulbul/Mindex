import { ArrowRight, Eye, FlaskConical } from 'lucide-react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useLocation, useNavigate } from 'react-router'
import { ApiError } from '@/api/client'
import { useAuth } from '@/auth/AuthContext'
import { BrandMark } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/primitives'
import { loginSchema, type LoginForm } from '@/lib/schemas'
import { DEMO_USERS } from '@/mocks/fixtures'

const DEMO_PASSWORD = 'mindex-demo'

export function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/experiments'

  const {
    register,
    handleSubmit,
    setValue,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<LoginForm>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  })

  if (user) return <Navigate to={from} replace />

  const onSubmit = handleSubmit(async (values) => {
    try {
      await login(values)
      await navigate(from, { replace: true })
    } catch (err) {
      setError('root', {
        message: err instanceof ApiError ? err.message : 'Sunucuya ulaşılamadı.',
      })
    }
  })

  const fillDemo = (email: string) => {
    setValue('email', email, { shouldValidate: true })
    setValue('password', DEMO_PASSWORD, { shouldValidate: true })
  }

  return (
    <main className="grid min-h-dvh lg:h-dvh lg:grid-cols-[minmax(0,1.15fr)_minmax(440px,0.85fr)] lg:overflow-hidden">
      <BrandPanel />

      <div className="relative flex items-center justify-center px-4 py-10 sm:px-8">
        <div className="w-full max-w-[400px] animate-rise">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <BrandMark className="size-10" />
            <span className="text-lg font-semibold tracking-tight">Mindex</span>
          </div>

          {/* 1px gradient rim around the glass card */}
          <div className="rounded-3xl bg-[linear-gradient(160deg,oklch(1_0_0/0.2),oklch(1_0_0/0.02)_40%,oklch(1_0_0/0.1))] p-px shadow-[0_30px_80px_-30px_oklch(0_0_0/0.8)]">
            <div className="rounded-[calc(1.5rem-1px)] glass bg-[rgb(18_19_22/0.6)] p-7 sm:p-8">
              <h1 className="text-headline text-[2.25rem] leading-none font-semibold tracking-[-0.04em]">
                Mindex Arena
              </h1>
              <p className="mt-1.5 text-sm text-muted-foreground">
                Birlikte öğrenen kripto ticaret ajanları
              </p>

              <form onSubmit={onSubmit} noValidate className="mt-7 space-y-4">
                <Field label="E-posta" htmlFor="email" error={errors.email?.message}>
                  <Input
                    id="email"
                    type="email"
                    autoComplete="username"
                    placeholder="ad@mindex.dev"
                    aria-invalid={!!errors.email}
                    className="h-10"
                    {...register('email')}
                  />
                </Field>
                <Field label="Parola" htmlFor="password" error={errors.password?.message}>
                  <Input
                    id="password"
                    type="password"
                    autoComplete="current-password"
                    aria-invalid={!!errors.password}
                    className="h-10"
                    {...register('password')}
                  />
                </Field>
                {errors.root && (
                  <p
                    role="alert"
                    className="rounded-xl border border-destructive/35 bg-destructive/[0.08] px-3 py-2 text-sm text-destructive"
                  >
                    {errors.root.message}
                  </p>
                )}
                <Button type="submit" className="h-11 w-full text-[15px]" disabled={isSubmitting}>
                  {isSubmitting ? 'Giriş yapılıyor…' : 'Giriş yap'}
                  {!isSubmitting && <ArrowRight aria-hidden />}
                </Button>
              </form>

              <div className="mt-7">
                <div className="flex items-center gap-3">
                  <span className="h-px flex-1 bg-border" />
                  <span className="eyebrow">Demo hesapları</span>
                  <span className="h-px flex-1 bg-border" />
                </div>
                <div className="mt-3 grid gap-2">
                  {Object.entries(DEMO_USERS).map(([email, { role }]) => (
                    <Button
                      key={email}
                      variant="outline"
                      className="group h-auto justify-start rounded-2xl px-3 py-2.5 text-left"
                      onClick={() => fillDemo(email)}
                    >
                      <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-primary/15 text-primary ring-1 ring-primary/25">
                        {role === 'researcher' ? <FlaskConical /> : <Eye />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13px]">
                          {role === 'researcher' ? 'Araştırmacı' : 'İzleyici'} · {email}
                        </span>
                        <span className="block text-[11px] font-normal text-muted-foreground">
                          {role === 'researcher'
                            ? 'Deney kurar, başlatır, dışa aktarır'
                            : 'Sonuçları ve ajanları izler'}
                        </span>
                      </span>
                      <ArrowRight
                        aria-hidden
                        className="text-muted-foreground opacity-0 transition-all group-hover:translate-x-0.5 group-hover:opacity-100"
                      />
                    </Button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <p className="mt-6 text-center text-xs text-muted-foreground">
            Sahte API · gerçek para kullanılmaz
          </p>
        </div>
      </div>
    </main>
  )
}

/** Left half of the login screen: product statement over the shared arena preview. */
function BrandPanel() {
  return (
    <aside className="relative hidden lg:flex lg:flex-col lg:justify-between lg:gap-10 lg:p-12 xl:p-14">
      <div className="flex items-center gap-3">
        <Link to="/" className="flex items-center gap-3">
          <BrandMark className="size-9" />
          <span className="text-lg font-semibold tracking-tight">Mindex</span>
        </Link>
        <span className="rounded-full border bg-white/[0.04] px-2 py-0.5 text-[11px] text-muted-foreground">
          Araştırma prototipi
        </span>
      </div>

      <div className="max-w-3xl">
        <h2 className="text-headline pb-2 text-5xl leading-[1.02] font-semibold tracking-[-0.045em] text-balance xl:text-6xl">
          Piyasayı tek başına değil, <em className="text-brand not-italic">birlikte öğrenen</em>{' '}
          ajanlar.
        </h2>
        <p className="mt-4 max-w-lg text-[15px] leading-relaxed text-muted-foreground">
          LLM ajanları kalıcı hafıza ve güven ağırlıklı bir forumla aynı piyasada yarışır. Her
          karar, dayandığı ders ve mesajla izlenebilir.
        </p>
      </div>

      <p className="text-xs text-muted-foreground">
        Bitirme projesi · tüm veriler sahte · gerçek para kullanılmaz
      </p>
    </aside>
  )
}
