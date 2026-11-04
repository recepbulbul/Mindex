import { useEffect, useRef } from 'react'
import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
  createSeriesMarkers,
  LastPriceAnimationMode,
  LineSeries,
  LineStyle,
  type DeepPartial,
  type ChartOptions,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts'
import type { Candle } from '@/api/types'

// lightweight-charts paints on canvas and does not read CSS variables, so colours are literal.
const CHART_COLORS = {
  up: '#5fdcb0',
  down: '#ff7d93',
  grid: 'rgba(255, 255, 255, 0.035)',
  text: '#6f7890',
  crosshair: 'rgba(255, 255, 255, 0.18)',
  label: '#1a2133',
}

// Categorical palette tuned for the dark card surface (distinct hue and lightness steps).
const SERIES_PALETTE = [
  '#4f86d9',
  '#c8743f',
  '#2fa07c',
  '#b48c24',
  '#c7608a',
  '#3f8f3f',
  '#8f7ae0',
  '#d0605c',
  '#8f8a80',
]

// Axis labels in Turkish number format, without needless decimals.
const priceFormat = new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 0 })
const smallFormat = new Intl.NumberFormat('tr-TR', { maximumFractionDigits: 2 })

const baseOptions: DeepPartial<ChartOptions> = {
  autoSize: true,
  localization: {
    locale: 'tr-TR',
    priceFormatter: (p: number) => (Math.abs(p) >= 100 ? priceFormat : smallFormat).format(p),
  },
  // Modern exchange look: no frame, no vertical grid, faint horizontals, sans axis labels.
  // The TradingView attribution required by the licence lives in the app footer instead (also printed).
  layout: {
    background: { type: ColorType.Solid, color: 'transparent' },
    textColor: CHART_COLORS.text,
    fontFamily: "'Manrope Variable', ui-sans-serif, sans-serif",
    fontSize: 11,
    attributionLogo: false,
  },
  grid: { vertLines: { visible: false }, horzLines: { color: CHART_COLORS.grid } },
  crosshair: {
    mode: CrosshairMode.Magnet,
    vertLine: { visible: false, labelBackgroundColor: CHART_COLORS.label },
    horzLine: {
      color: CHART_COLORS.crosshair,
      style: LineStyle.Dashed,
      labelBackgroundColor: CHART_COLORS.label,
    },
  },
  rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.12, bottom: 0.08 } },
  timeScale: { borderVisible: false, rightOffset: 3 },
}

export interface TradeMarker {
  time: string
  side: 'buy' | 'sell'
  label: string
}

export function CandleChart({
  candles,
  markers,
  height = 360,
  label,
}: {
  candles: Candle[]
  markers: TradeMarker[]
  /** Pixels, or any CSS length (the chart sizes itself to its box). */
  height?: number | string
  label: string
}) {
  const el = useRef<HTMLDivElement>(null)
  const chartApi = useRef<IChartApi | null>(null)
  const series = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const markerApi = useRef<ISeriesMarkersPluginApi<Time> | null>(null)

  useEffect(() => {
    const chart = createChart(el.current!, baseOptions)
    chartApi.current = chart
    series.current = chart.addSeries(CandlestickSeries, {
      upColor: CHART_COLORS.up,
      downColor: CHART_COLORS.down,
      wickUpColor: CHART_COLORS.up,
      wickDownColor: CHART_COLORS.down,
      borderVisible: false,
    })
    markerApi.current = createSeriesMarkers(series.current, [])
    return () => {
      chartApi.current = null
      series.current = null
      markerApi.current = null
      chart.remove()
    }
  }, [])

  useEffect(() => {
    series.current?.setData(candles.map((c) => ({ ...c, time: c.time as Time })))
    chartApi.current?.timeScale().fitContent()
  }, [candles])

  useEffect(() => {
    markerApi.current?.setMarkers(
      markers.map((m): SeriesMarker<Time> => ({
        time: m.time as Time,
        position: m.side === 'buy' ? 'belowBar' : 'aboveBar',
        shape: m.side === 'buy' ? 'arrowUp' : 'arrowDown',
        color: m.side === 'buy' ? CHART_COLORS.up : CHART_COLORS.down,
        text: m.label,
      })),
    )
  }, [markers])

  // The canvas has no text of its own, so the figure's label is what screen readers announce.
  return <div ref={el} role="figure" aria-label={label} style={{ height }} />
}

export interface LineData {
  id: string
  name: string
  points: { time: string; value: number }[]
  /** Series colour; defaults to the categorical palette by position. */
  color?: string
}

export function MultiLineChart({
  lines,
  height = 260,
  label,
}: {
  lines: LineData[]
  /** Pixels, or any CSS length (the chart sizes itself to its box). */
  height?: number | string
  label: string
}) {
  const el = useRef<HTMLDivElement>(null)

  // Rebuild the chart when the (memoised) lines change; simpler than diffing series.
  useEffect(() => {
    const c = createChart(el.current!, baseOptions)
    // A single series gets a soft area fill; several series stay as plain lines.
    const created = lines.map((line, i) => {
      const color = line.color ?? SERIES_PALETTE[i % SERIES_PALETTE.length]!
      const common = {
        lineWidth: 2,
        crosshairMarkerRadius: 3,
        priceLineVisible: false,
        lastValueVisible: false,
        // A slow pulse on the latest point keeps the race feeling live.
        lastPriceAnimation: LastPriceAnimationMode.Continuous,
      } as const
      return lines.length === 1
        ? c.addSeries(AreaSeries, {
            ...common,
            lineColor: color,
            topColor: `${color}40`,
            bottomColor: `${color}00`,
          })
        : c.addSeries(LineSeries, { ...common, color })
    })
    created.forEach((s, i) =>
      s.setData(lines[i]!.points.map((p) => ({ time: p.time as Time, value: p.value }))),
    )
    c.timeScale().fitContent()
    return () => c.remove()
  }, [lines])

  return (
    <div>
      <div ref={el} role="figure" aria-label={label} style={{ height }} />
      {lines.length > 1 && (
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
          {lines.map((line, i) => (
            <li key={line.id} className="flex items-center gap-1.5">
              <span
                aria-hidden
                className="h-0.5 w-3 rounded-full"
                style={{ background: line.color ?? SERIES_PALETTE[i % SERIES_PALETTE.length] }}
              />
              {line.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
