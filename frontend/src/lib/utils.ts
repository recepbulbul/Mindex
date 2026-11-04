import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

const usdWith = (digits: number) =>
  new Intl.NumberFormat('tr-TR', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
// Built once: Intl formatters are expensive and prices update on every replay tick.
const usd = usdWith(0)
const usd2 = usdWith(2)
const usd4 = usdWith(4)
const pct = new Intl.NumberFormat('tr-TR', {
  style: 'percent',
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
  signDisplay: 'exceptZero',
})
const num = new Intl.NumberFormat('tr-TR', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: 'negative',
})

export const formatUsd = (v: number) => usd.format(v)
/** Coin prices: whole dollars for BTC-sized prices, more decimals as the price gets smaller. */
export const formatPrice = (v: number) => (v < 10 ? usd4 : v < 1000 ? usd2 : usd).format(v)
export const formatPct = (v: number) => pct.format(v)
export const formatNum = (v: number) => num.format(v)
const shortDate = new Intl.DateTimeFormat('tr-TR', {
  day: '2-digit',
  month: 'short',
  timeZone: 'UTC',
})
const longDate = new Intl.DateTimeFormat('tr-TR', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})
const utcDay = (iso: string) => new Date(`${iso}T00:00:00Z`)
export const formatShortDate = (iso: string) => shortDate.format(utcDay(iso))
export const formatDate = (iso: string) => longDate.format(utcDay(iso))
