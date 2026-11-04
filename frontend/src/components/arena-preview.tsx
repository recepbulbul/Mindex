import { AgentAvatar } from '@/components/identity'
import { agentColor } from '@/lib/identity'
import { cn } from '@/lib/utils'

// Decorative race shown on the landing and login pages; figures match the prototype report.
const RACE = [
  {
    id: 'llm-momentum',
    name: 'LLM · Momentum',
    ret: '+%65,8',
    path: 'M0 210 C60 205 90 190 140 196 S230 150 300 160 S420 90 480 98 S600 40 680 30',
  },
  {
    id: 'llm-risk-averse',
    name: 'LLM · Riskten kaçınan',
    ret: '+%24,6',
    path: 'M0 210 C70 208 110 200 170 202 S280 178 350 182 S470 150 540 156 S640 138 680 140',
  },
  {
    id: 'llm-mean-reversion',
    name: 'LLM · Ortalamaya dönüş',
    ret: '+%28,3',
    path: 'M0 210 C60 214 120 206 180 200 S300 186 370 170 S500 160 560 150 S650 146 680 148',
  },
  {
    id: 'buy-hold-btc',
    name: 'Al-ve-tut BTC',
    ret: '+%28,1',
    path: 'M0 210 C50 220 100 234 160 226 S270 200 330 214 S450 170 520 160 S630 150 680 152',
  },
]

/** Product shot built from real UI parts: a leaderboard beside the equity race. */
export function ArenaPreview({ className }: { className?: string }) {
  return (
    <div className={cn('relative', className)}>
      <figure
        aria-label="Arena önizlemesi: dört ajanın portföy değeri yarışı ve lider tablosu"
        className="relative overflow-hidden rounded-3xl border glass"
      >
        <div className="flex items-center gap-2 border-b px-4 py-3">
          <span className="flex gap-1.5" aria-hidden>
            <span className="size-2.5 rounded-full bg-white/10" />
            <span className="size-2.5 rounded-full bg-white/10" />
            <span className="size-2.5 rounded-full bg-white/10" />
          </span>
          <span className="ml-3 text-[11px] num text-muted-foreground">
            mindex / deneyler / test-dönemi-c3 / canlı
          </span>
          <span className="ml-auto flex items-center gap-1.5 text-[11px] num text-up">
            <span className="size-1.5 rounded-full bg-up" aria-hidden /> 183 gün · replay
          </span>
        </div>

        <div className="grid lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="border-b p-5 lg:border-r lg:border-b-0">
            <div className="flex items-baseline justify-between">
              <p className="text-sm font-medium">Portföy değeri</p>
              <p className="text-[11px] num text-muted-foreground">başlangıç 10.000 $</p>
            </div>
            <svg viewBox="0 0 680 240" className="mt-4 h-56 w-full" aria-hidden>
              {[60, 120, 180].map((y) => (
                <line key={y} x1="0" x2="680" y1={y} y2={y} stroke="rgb(255 255 255 / 0.05)" />
              ))}
              <line
                x1="0"
                x2="680"
                y1="210"
                y2="210"
                stroke="rgb(255 255 255 / 0.18)"
                strokeDasharray="3 5"
              />
              {RACE.map((r) => (
                <path
                  key={r.id}
                  d={r.path}
                  fill="none"
                  stroke={agentColor(r.id)}
                  strokeWidth={r.id === 'llm-momentum' ? 2.25 : 1.5}
                  strokeOpacity={r.id === 'llm-momentum' ? 1 : 0.75}
                  strokeLinecap="round"
                />
              ))}
              <circle cx="680" cy="30" r="4" fill={agentColor('llm-momentum')} />
            </svg>
            <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted-foreground">
              {RACE.map((r) => (
                <li key={r.id} className="flex items-center gap-1.5">
                  <span
                    aria-hidden
                    className="h-0.5 w-3 rounded-full"
                    style={{ background: agentColor(r.id) }}
                  />
                  {r.name.replace('LLM · ', '')}
                </li>
              ))}
            </ul>
          </div>

          <div className="p-5">
            <p className="text-sm font-medium">Lider tablosu</p>
            <ol className="mt-4 space-y-1">
              {[...RACE]
                .sort((a, b) => parseFloat(b.ret.slice(2)) - parseFloat(a.ret.slice(2)))
                .map((r, i) => (
                  <li
                    key={r.id}
                    className={cn(
                      'flex items-center gap-3 rounded-lg px-2 py-2 text-[13px]',
                      i === 0 && 'bg-white/[0.04]',
                    )}
                  >
                    <span
                      className={cn(
                        'w-3 text-[11px] num',
                        i === 0 ? 'text-primary' : 'text-muted-foreground',
                      )}
                    >
                      {i + 1}
                    </span>
                    <AgentAvatar id={r.id} name={r.name} className="size-6 text-[9px]" />
                    <span className="flex-1 truncate">{r.name}</span>
                    <span className="text-xs num text-up">{r.ret}</span>
                  </li>
                ))}
            </ol>
            <div className="mt-5 grid grid-cols-2 divide-x overflow-hidden rounded-xl border text-xs">
              <div className="p-3">
                <p className="text-muted-foreground">MDD azalması</p>
                <p className="mt-1 text-lg num text-foreground">%47,9</p>
              </div>
              <div className="p-3">
                <p className="text-muted-foreground">Sürü korelasyonu</p>
                <p className="mt-1 text-lg num text-foreground">0,06</p>
              </div>
            </div>
          </div>
        </div>
      </figure>
    </div>
  )
}
