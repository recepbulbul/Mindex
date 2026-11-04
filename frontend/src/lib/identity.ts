import type { Asset } from '@/api/types'

/**
 * Agent identity colours: a jewel-tone categorical palette (sapphire, copper, jade, gold, rose,
 * green, amethyst, garnet), assigned to entities in fixed order. Validated with the dataviz
 * checker on the glass surface (#121316), dark mode, adjacent pairs: all checks pass — worst
 * CVD ΔE 8.7, normal-vision ΔE 15.8, every slot inside L 0.48–0.67 and ≥ 3:1. The colour follows
 * the agent on every screen; the BTC benchmark is warm grey so it reads as a reference line.
 */
const AGENT_COLOR: Record<string, string> = {
  'llm-momentum': '#4f86d9',
  'llm-mean-reversion': '#c8743f',
  'llm-sentiment': '#2fa07c',
  'llm-risk-averse': '#b48c24',
  'ma-cross': '#c7608a',
  'equal-weight': '#3f8f3f',
  ppo: '#8f7ae0',
  'mcp-guest': '#d0605c',
  'buy-hold-btc': '#8f8a80',
}
const FALLBACK = ['#4f86d9', '#c8743f', '#2fa07c']

export function agentColor(id: string) {
  if (AGENT_COLOR[id]) return AGENT_COLOR[id]
  const h = [...id].reduce((s, c) => s + c.charCodeAt(0), 0)
  return FALLBACK[h % FALLBACK.length]!
}

/** "LLM · Ortalamaya dönüş" → "OD", "PPO" → "PP". */
export function agentInitials(name: string) {
  const clean = name
    .replace(/^LLM · /, '')
    .replace(/\(.*\)/, '')
    .trim()
  const words = clean.split(/[\s-]+/).filter(Boolean)
  const letters = words.length > 1 ? words[0]![0]! + words[1]![0]! : clean.slice(0, 2)
  return letters.toLocaleUpperCase('tr-TR')
}

/** Brand colours of the traded coins, used for ticker orbs. */
export const ASSET_COLOR: Record<Asset, string> = {
  BTC: '#f7931a',
  ETH: '#8c8cff',
  SOL: '#14f195',
  BNB: '#f3ba2f',
  XRP: '#7fb2ff',
}
