import type { Experiment } from '@/api/types'

// The experiment YAML of GET /experiments/:id/export.yaml and POST /experiments/import.
// The backend uses PyYAML; the mock only needs this one shape, so it carries a tiny
// reader for it (scalars, one level of nesting, inline `[a, b]` or block `- a` lists)
// instead of a YAML library in the demo bundle.

export function experimentToYaml(exp: Experiment): string {
  return [
    `# Mindex deney yapılandırması (F2)`,
    `name: ${JSON.stringify(exp.name)}`,
    `mode: ${exp.mode}`,
    `condition: ${exp.condition}`,
    `period:`,
    `  start: ${exp.startDate}`,
    `  end: ${exp.endDate ?? 'null'}`,
    `assets: [${exp.assets.join(', ')}]`,
    `agents:`,
    ...exp.agentIds.map((a) => `  - ${a}`),
    `seed: ${exp.seed}`,
    `execution:`,
    `  commission_rate: ${yamlNumber(exp.commissionRate)}`,
    `  slippage_bps: ${yamlNumber(exp.slippageBps)}`,
    `llm:`,
    `  model: ${exp.modelVersion}`,
    `  prompt_version: ${exp.promptVersion}`,
    '',
  ].join('\n')
}

// JS writes 1e-7, which YAML 1.1 (PyYAML) reads as a string: always write plain decimals.
function yamlNumber(x: number): string {
  const s = String(x)
  return /e/i.test(s) ? x.toFixed(20).replace(/\.?0+$/, '') : s
}

type Value = string | number | null | Value[] | { [key: string]: Value }

function scalar(raw: string): Value {
  const s = raw.trim()
  if (s === 'null' || s === '~' || s === '') return null
  if (/^".*"$/.test(s)) return JSON.parse(s) as string
  if (/^'.*'$/.test(s)) return s.slice(1, -1).replaceAll("''", "'")
  if (/^\[.*\]$/.test(s))
    return s
      .slice(1, -1)
      .split(',')
      .map((x) => x.trim())
      .filter(Boolean)
      .map(scalar)
  if (/^-?\d+(\.\d+)?(e-?\d+)?$/i.test(s)) return Number(s)
  return s
}

/** Parses the export shape; throws on anything else (the handler answers 422). */
export function parseYaml(text: string): Record<string, Value> {
  const root: Record<string, Value> = {}
  let open: { key: string; target: Record<string, Value> } | null = null
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim() || line.trimStart().startsWith('#')) continue
    const indented = /^\s/.test(line)
    const item = /^\s*-\s+(.*)$/.exec(line)
    if (item && open) {
      const list = open.target[open.key]
      if (list === null) open.target[open.key] = [scalar(item[1]!)]
      else if (Array.isArray(list)) list.push(scalar(item[1]!))
      else throw new Error('liste beklenmiyordu')
      continue
    }
    const pair = /^\s*([A-Za-z_]+):(?:\s+(.*))?$/.exec(line)
    if (!pair) throw new Error(`okunamayan satır: ${line}`)
    const [, key, rest] = pair as unknown as [string, string, string | undefined]
    if (!indented) {
      if (rest === undefined) {
        root[key] = null // a nested map or a block list follows
        open = { key, target: root }
      } else {
        root[key] = scalar(rest)
        open = null
      }
    } else {
      if (!open) throw new Error(`beklenmeyen girinti: ${line}`)
      let map = open.target[open.key]
      if (map === null) map = open.target[open.key] = {}
      if (typeof map !== 'object' || Array.isArray(map)) throw new Error('eşleme beklenmiyordu')
      map[key] = scalar(rest ?? '')
    }
  }
  return root
}
