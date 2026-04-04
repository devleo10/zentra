"use client"

import { ReactNode, useEffect, useMemo, useState } from "react"
import {
  ApiError,
  pingKeepAlive,
  runV2Analysis,
  TimeFrame,
  V2AnalysisMeta,
  V2AnalysisProgress,
  V2AnalysisResult,
} from "@/lib/api"

const TIMEFRAMES: Array<{ value: TimeFrame; label: string }> = [
  { value: "current", label: "Now" },
  { value: "week", label: "7D" },
  { value: "month", label: "1M" },
]

const REFRESH_TOOLTIP = "Runs a fresh backend analysis."
const MAX_NEWS_ITEMS = 6

const GEO_KEYWORDS = [
  "war",
  "geopolit",
  "sanction",
  "tariff",
  "middle east",
  "ukraine",
  "china",
  "taiwan",
  "oil shock",
  "conflict",
  "ceasefire",
  "nato",
]

const FED_KEYWORDS = [
  "fed",
  "fomc",
  "powell",
  "rate",
  "minutes",
  "balance sheet",
  "dot plot",
  "policy",
]

type Direction = "up" | "down" | "flat"
type HeadlineItem = V2AnalysisResult["top_headlines"][number]

interface ReleaseRow {
  indicator: string
  nextReleaseDate: string | null
  latestKnownDate: string | null
}

function normalizeText(value: string | null | undefined): string {
  return (value ?? "").toLowerCase()
}

function toTitleCase(value: string | null | undefined): string {
  if (!value) return "N/A"
  return value
    .replace(/[_-]+/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ")
}

function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return "N/A"
  return value.toFixed(digits)
}

function formatPercent(value: number | null | undefined, digits = 2, signed = true): string {
  if (value == null || !Number.isFinite(value)) return "N/A"
  const sign = signed && value > 0 ? "+" : ""
  return `${sign}${value.toFixed(digits)}%`
}

function formatPrice(value: number | null | undefined, digits = 0): string {
  if (value == null || !Number.isFinite(value)) return "N/A"
  return `$${value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`
}

function formatDateLabel(value: string | null | undefined): string {
  if (!value) return "TBD"
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
  }).format(parsed)
}

function directionFromNumber(value: number | null | undefined, epsilon = 0.01): Direction {
  if (value == null || !Number.isFinite(value)) return "flat"
  if (value > epsilon) return "up"
  if (value < -epsilon) return "down"
  return "flat"
}

function directionFromText(value: string | null | undefined): Direction {
  const text = normalizeText(value)
  if (!text) return "flat"

  const upWords = ["up", "increase", "rising", "expand", "hawkish", "steepen", "risk on", "bull"]
  const downWords = ["down", "decrease", "fall", "contract", "dovish", "invert", "risk off", "bear"]

  if (upWords.some((word) => text.includes(word))) return "up"
  if (downWords.some((word) => text.includes(word))) return "down"
  return "flat"
}

function directionFromArrow(value: "up" | "down" | null | undefined): Direction {
  if (value === "up") return "up"
  if (value === "down") return "down"
  return "flat"
}

function btcPercentChangeForTimeframe(
  r: V2AnalysisResult,
  tf: TimeFrame,
): number | null {
  if (tf === "current") {
    const v = r.btc_change_24h ?? r.btc_change
    return v != null && Number.isFinite(v) ? v : null
  }
  if (tf === "week") {
    const v = r.btc_change_7d ?? r.btc_change
    return v != null && Number.isFinite(v) ? v : null
  }
  const v = r.btc_change
  return v != null && Number.isFinite(v) ? v : null
}

function directionLabel(direction: Direction): string {
  if (direction === "up") return "up"
  if (direction === "down") return "down"
  return "flat"
}

function directionClass(direction: Direction): string {
  if (direction === "up") return "text-green-400"
  if (direction === "down") return "text-red-400"
  return "text-gray-400"
}

function pickLatestCheckDate(result: V2AnalysisResult | null, patterns: string[]): string | null {
  const checks = result?.data_freshness_info?.checks ?? []
  const matchedDates = checks
    .filter((check) => {
      const name = normalizeText(check.name)
      return patterns.some((pattern) => name.includes(pattern))
    })
    .map((check) => check.data_date)
    .filter((date): date is string => !!date)

  if (matchedDates.length === 0) return null
  return [...matchedDates].sort().at(-1) ?? null
}

function estimateNextReleaseDate(latestDate: string | null, cadenceMonths: number): string | null {
  if (!latestDate) return null
  const parsed = new Date(latestDate)
  if (Number.isNaN(parsed.getTime())) return null
  const next = new Date(parsed)
  next.setMonth(next.getMonth() + cadenceMonths)
  return next.toISOString().slice(0, 10)
}

function spreadCondition(spread: number | null | undefined): string {
  if (spread == null || !Number.isFinite(spread)) return "N/A"
  if (spread > 0) return "Steepening"
  if (spread < 0) return "Inversion"
  return "Neutral"
}

function average(values: number[]): number | null {
  if (values.length === 0) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function timeAgo(timestamp: string | null | undefined): string {
  if (!timestamp) return "unknown"
  const ts = new Date(timestamp).getTime()
  if (!Number.isFinite(ts)) return "unknown"
  const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000))
  if (diffSec < 60) return `${Math.max(1, diffSec)}s ago`
  const mins = Math.floor(diffSec / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

function SectionCard({
  number,
  title,
  note,
  children,
}: {
  number: number
  title: string
  note?: string
  children: ReactNode
}) {
  return (
    <section className="rounded-xl border border-gray-800 bg-gray-900/80 p-4 sm:p-5 space-y-3">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-800 pb-2">
        <h2 className="text-sm sm:text-base font-semibold tracking-wide text-gray-100">
          {number}) {title}
        </h2>
        {note ? (
          <span className="rounded-full border border-gray-700 px-2 py-0.5 text-[10px] sm:text-xs text-gray-300">
            {note}
          </span>
        ) : null}
      </header>
      {children}
    </section>
  )
}

function DirectionTag({ direction }: { direction: Direction }) {
  return <span className={`text-xs font-medium ${directionClass(direction)}`}>({directionLabel(direction)})</span>
}

function MetricRow({
  label,
  value,
  direction,
  detail,
}: {
  label: string
  value: string
  direction?: Direction
  detail?: string
}) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-950/60 px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm text-gray-300">{label}</span>
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-white">{value}</span>
          {direction ? <DirectionTag direction={direction} /> : null}
        </div>
      </div>
      {detail ? <p className="mt-1 text-xs text-gray-500">{detail}</p> : null}
    </div>
  )
}

function NewsList({ items, emptyLabel }: { items: HeadlineItem[]; emptyLabel: string }) {
  if (items.length === 0) {
    return <p className="text-sm text-gray-400">{emptyLabel}</p>
  }

  return (
    <ul className="list-disc list-inside space-y-2 text-sm text-gray-200">
      {items.map((headline, index) => (
        <li key={`${headline.source}-${index}`}>
          <span>{headline.title}</span>
          <span className="text-xs text-gray-500"> ({headline.source || "source n/a"})</span>
        </li>
      ))}
    </ul>
  )
}

export default function BtcMacroDashboardNew() {
  const [timeframe, setTimeframe] = useState<TimeFrame>("current")
  const [results, setResults] = useState<Partial<Record<TimeFrame, V2AnalysisResult>>>({})
  const [resultMeta, setResultMeta] = useState<Partial<Record<TimeFrame, V2AnalysisMeta>>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [retryInSec, setRetryInSec] = useState(0)
  const [clickCooldownSec, setClickCooldownSec] = useState(0)
  const [pollMessage, setPollMessage] = useState<string | null>(null)
  const [pollRetryInSec, setPollRetryInSec] = useState(0)

  const result = results[timeframe] ?? null
  const nonChangeableResult = results.current ?? result
  const meta = resultMeta[timeframe] ?? null

  useEffect(() => {
    if (retryInSec <= 0) return
    const timer = setInterval(() => {
      setRetryInSec((value) => (value > 0 ? value - 1 : 0))
    }, 1000)
    return () => clearInterval(timer)
  }, [retryInSec])

  useEffect(() => {
    if (clickCooldownSec <= 0) return
    const timer = setInterval(() => {
      setClickCooldownSec((value) => (value > 0 ? value - 1 : 0))
    }, 1000)
    return () => clearInterval(timer)
  }, [clickCooldownSec])

  useEffect(() => {
    if (!loading || pollRetryInSec <= 0) return
    const timer = setInterval(() => {
      setPollRetryInSec((value) => (value > 0 ? value - 1 : 0))
    }, 1000)
    return () => clearInterval(timer)
  }, [loading, pollRetryInSec])

  useEffect(() => {
    pingKeepAlive()
    const interval = setInterval(() => {
      pingKeepAlive()
    }, 4 * 60 * 1000)
    return () => clearInterval(interval)
  }, [])

  const handleAnalyze = async () => {
    if (loading || retryInSec > 0 || clickCooldownSec > 0) return
    if (meta?.refreshInProgress) {
      setError("Analysis is already running on backend. Waiting for completion.")
      return
    }

    setLoading(true)
    setError(null)
    setPollMessage("Starting analysis on backend...")
    setPollRetryInSec(0)

    try {
      const response = await runV2Analysis(timeframe, (progress: V2AnalysisProgress) => {
        setPollMessage(progress.message)
        setPollRetryInSec(progress.nextRetryInSeconds)
      })
      setResults((prev) => ({ ...prev, [timeframe]: response.data }))
      setResultMeta((prev) => ({ ...prev, [timeframe]: response.meta }))
      setRetryInSec(0)
      setClickCooldownSec(4)

      if (timeframe !== "current" && !results.current) {
        setResults((prev) => ({ ...prev, current: response.data }))
      }
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 429) {
        const wait = err.retryAfterSeconds ?? 15
        setRetryInSec(wait)
        setError(`Backend is temporarily busy. Try again in ${wait}s.`)
      } else {
        setError(err instanceof Error ? err.message : "Analysis failed")
      }
    } finally {
      setLoading(false)
      setPollRetryInSec(0)
    }
  }

  const activeHeadlines: HeadlineItem[] = result?.top_headlines ?? []

  const geopoliticsNews = useMemo(() => {
    return activeHeadlines
      .filter((headline) => {
        const title = normalizeText(headline.title)
        if (headline.risk_impact === "risk_off") return true
        return GEO_KEYWORDS.some((word) => title.includes(word))
      })
      .slice(0, MAX_NEWS_ITEMS)
  }, [activeHeadlines])

  const fedNews = useMemo(() => {
    return activeHeadlines
      .filter((headline) => {
        const title = normalizeText(headline.title)
        return FED_KEYWORDS.some((word) => title.includes(word))
      })
      .slice(0, MAX_NEWS_ITEMS)
  }, [activeHeadlines])

  const fedLatestDate = pickLatestCheckDate(nonChangeableResult, ["fed", "fomc", "balance", "policy"])
  const fedNextReleaseDate = estimateNextReleaseDate(fedLatestDate, 1)

  const releaseRows: ReleaseRow[] = useMemo(() => {
    const cpiLatest = pickLatestCheckDate(nonChangeableResult, ["cpi"])
    const pceLatest = pickLatestCheckDate(nonChangeableResult, ["pce"])
    const gdpLatest = pickLatestCheckDate(nonChangeableResult, ["gdp"])
    const pmiLatest = pickLatestCheckDate(nonChangeableResult, ["pmi", "ism"])
    const m2Latest = pickLatestCheckDate(nonChangeableResult, ["m2"])
    const unemploymentLatest = pickLatestCheckDate(nonChangeableResult, ["unemployment", "jobs"])

    return [
      {
        indicator: "CPI (MoM)",
        nextReleaseDate: estimateNextReleaseDate(cpiLatest, 1),
        latestKnownDate: cpiLatest,
      },
      {
        indicator: "Core CPI (MoM)",
        nextReleaseDate: estimateNextReleaseDate(cpiLatest, 1),
        latestKnownDate: cpiLatest,
      },
      {
        indicator: "PCE (MoM)",
        nextReleaseDate: estimateNextReleaseDate(pceLatest, 1),
        latestKnownDate: pceLatest,
      },
      {
        indicator: "GDP (Quarterly)",
        nextReleaseDate: estimateNextReleaseDate(gdpLatest, 3),
        latestKnownDate: gdpLatest,
      },
      {
        indicator: "PMI (MoM)",
        nextReleaseDate: estimateNextReleaseDate(pmiLatest, 1),
        latestKnownDate: pmiLatest,
      },
      {
        indicator: "M2 (MoM)",
        nextReleaseDate: estimateNextReleaseDate(m2Latest, 1),
        latestKnownDate: m2Latest,
      },
      {
        indicator: "Unemployment Rate",
        nextReleaseDate: estimateNextReleaseDate(unemploymentLatest, 1),
        latestKnownDate: unemploymentLatest,
      },
    ]
  }, [nonChangeableResult])

  const monthlyYieldRows = nonChangeableResult?.yield_monthly_track?.slice(-3) ?? []
  const spreadAverage3m = average(monthlyYieldRows.map((row) => row.spread))
  const btcTfPct = result ? btcPercentChangeForTimeframe(result, timeframe) : null

  const showActionButton = !result || loading || retryInSec > 0 || clickCooldownSec > 0

  return (
    <main className="min-h-screen bg-gray-950 text-white px-3 py-4 sm:px-6 sm:py-5">
      <div className="mx-auto w-full max-w-[1600px] space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight">BTC Macro Dashboard - New Format</h1>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex gap-1 rounded-xl border border-gray-800 bg-gray-900 p-1">
              {TIMEFRAMES.map((tf) => (
                <button
                  key={tf.value}
                  onClick={() => setTimeframe(tf.value)}
                  className={`rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors sm:px-3 sm:text-sm ${
                    timeframe === tf.value ? "bg-blue-600 text-white" : "text-gray-400 hover:text-white"
                  }`}
                >
                  {tf.label}
                </button>
              ))}
            </div>

            {showActionButton ? (
              <button
                onClick={handleAnalyze}
                title={REFRESH_TOOLTIP}
                disabled={loading || retryInSec > 0 || clickCooldownSec > 0 || !!meta?.refreshInProgress}
                className="whitespace-nowrap rounded-xl bg-blue-600 px-4 py-2 text-xs font-semibold transition-colors hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-400 sm:text-sm"
              >
                {loading
                  ? "Analyzing..."
                  : retryInSec > 0
                    ? `Wait ${retryInSec}s`
                    : clickCooldownSec > 0
                      ? `Refresh in ${clickCooldownSec}s`
                      : result
                        ? "Refresh now"
                        : "Run analysis"}
              </button>
            ) : null}
          </div>
        </div>

        {result ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
              <p className="text-xs text-gray-400">Final score</p>
              <p className="text-3xl font-bold text-white">{result.final_score}/100</p>
            </div>
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
              <p className="text-xs text-gray-400">Bias and action</p>
              <p className="text-lg font-semibold text-white">{result.bias}</p>
              <p className="text-sm text-gray-300">{result.action}</p>
            </div>
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
              <p className="text-xs text-gray-400">Last updated</p>
              <p className="text-sm font-medium text-white">{timeAgo(result.timestamp)}</p>
              <p className="text-xs text-gray-500">{formatDateLabel(result.timestamp)}</p>
            </div>
          </div>
        ) : null}

        {error ? (
          <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-200">{error}</div>
        ) : null}

        {loading ? (
          <div className="rounded-xl border border-blue-500/30 bg-blue-500/10 p-3 text-sm text-blue-200">
            {pollMessage ?? "Analysis in progress..."}
            {pollRetryInSec > 0 ? <span className="ml-2 text-blue-300">Retry in {pollRetryInSec}s</span> : null}
          </div>
        ) : null}

        {!result && !loading ? (
          <div className="rounded-xl border border-gray-800 bg-gray-900 p-4 text-sm text-gray-300">
            Run analysis to populate the new dashboard format.
          </div>
        ) : null}

        {result ? (
          <div className="space-y-4 pb-6">
            <SectionCard number={1} title="Key MacroGeopolitics News">
              <NewsList items={geopoliticsNews} emptyLabel="No geopolitics headlines in current snapshot." />
            </SectionCard>

            <SectionCard
              number={2}
              title="Key Macro Events News of FED"
              note={`Next release date: ${formatDateLabel(fedNextReleaseDate)}`}
            >
              <NewsList items={fedNews} emptyLabel="No FED event headlines in current snapshot." />
            </SectionCard>

            <SectionCard number={3} title="Next Release Date of Key Economic Indicators">
              <div className="overflow-x-auto">
                <table className="min-w-full text-left text-sm">
                  <thead className="text-xs uppercase tracking-wide text-gray-400">
                    <tr>
                      <th className="pb-2 pr-4">Indicator</th>
                      <th className="pb-2 pr-4">Next release date</th>
                      <th className="pb-2">Latest known data date</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800">
                    {releaseRows.map((row) => (
                      <tr key={row.indicator}>
                        <td className="py-2 pr-4 text-gray-200">{row.indicator}</td>
                        <td className="py-2 pr-4 text-gray-100">{formatDateLabel(row.nextReleaseDate)}</td>
                        <td className="py-2 text-gray-400">{formatDateLabel(row.latestKnownDate)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </SectionCard>

            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <SectionCard number={4} title="Inflation Metrics" note="Non-changeable with weekly and daily">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">A) CPI (MoM)</h3>
                <MetricRow
                  label="CPI (MoM)"
                  value={formatPercent(nonChangeableResult?.cpi_mom_change)}
                  direction={directionFromNumber(nonChangeableResult?.cpi_mom_change)}
                  detail={`Value: ${formatNumber(nonChangeableResult?.cpi_value, 3)}`}
                />
                <MetricRow
                  label="3-Month Avg CPI (MoM)"
                  value={formatPercent(nonChangeableResult?.cpi_mom_avg_3m)}
                  direction={
                    nonChangeableResult?.cpi_mom_avg_3m_trend
                      ? directionFromText(nonChangeableResult.cpi_mom_avg_3m_trend)
                      : directionFromNumber(
                          (nonChangeableResult?.cpi_mom_avg_3m ?? 0) - (nonChangeableResult?.cpi_mom_avg_3m_prior ?? 0),
                        )
                  }
                      detail={`Prior: ${formatPercent(nonChangeableResult?.cpi_mom_avg_3m_prior)} | Value: ${formatNumber(nonChangeableResult?.cpi_value, 3)}`}
                />

                <h3 className="pt-2 text-xs font-semibold uppercase tracking-wide text-gray-400">B) Core CPI (MoM)</h3>
                <MetricRow
                  label="Core CPI (MoM)"
                  value={formatPercent(nonChangeableResult?.cpi_core_mom_change)}
                  direction={directionFromNumber(nonChangeableResult?.cpi_core_mom_change)}
                  detail={`Value: ${formatNumber(nonChangeableResult?.core_cpi_value, 3)}`}
                />
                <MetricRow
                  label="3-Month Avg Core CPI (MoM)"
                  value={formatPercent(nonChangeableResult?.core_cpi_mom_avg_3m)}
                  direction={
                    nonChangeableResult?.core_cpi_mom_avg_3m_trend
                      ? directionFromText(nonChangeableResult.core_cpi_mom_avg_3m_trend)
                      : directionFromNumber(
                          (nonChangeableResult?.core_cpi_mom_avg_3m ?? 0) -
                            (nonChangeableResult?.core_cpi_mom_avg_3m_prior ?? 0),
                        )
                  }
                  detail={`Prior: ${formatPercent(nonChangeableResult?.core_cpi_mom_avg_3m_prior)} | Value: ${formatNumber(nonChangeableResult?.core_cpi_value, 3)}`}
                />

                <h3 className="pt-2 text-xs font-semibold uppercase tracking-wide text-gray-400">C) PCE (MoM)</h3>
                <MetricRow
                  label="PCE (MoM)"
                  value={formatPercent(nonChangeableResult?.pce_mom_change)}
                  direction={directionFromNumber(nonChangeableResult?.pce_mom_change)}
                  detail={`Value: ${formatNumber(nonChangeableResult?.pce_value, 3)}`}
                />
                <MetricRow
                  label="3-Month Avg PCE (MoM)"
                  value={formatPercent(nonChangeableResult?.pce_mom_avg_3m)}
                  direction={
                    nonChangeableResult?.pce_mom_avg_3m_trend
                      ? directionFromText(nonChangeableResult.pce_mom_avg_3m_trend)
                      : directionFromNumber(
                          (nonChangeableResult?.pce_mom_avg_3m ?? 0) - (nonChangeableResult?.pce_mom_avg_3m_prior ?? 0),
                        )
                  }
                  detail={`Prior: ${formatPercent(nonChangeableResult?.pce_mom_avg_3m_prior)} | Value: ${formatNumber(nonChangeableResult?.pce_value, 3)}`}
                />
              </SectionCard>

              <SectionCard number={5} title="Growth" note="Non-changeable with weekly and daily">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">A) GDP (Quarterly)</h3>
                <MetricRow
                  label="GDP (Quarterly)"
                  value={formatPercent(nonChangeableResult?.gdp_growth_rate)}
                  direction={directionFromText(nonChangeableResult?.gdp_trend)}
                  detail={`Value: ${formatPercent(nonChangeableResult?.gdp_growth_rate)} | Date: ${formatDateLabel(nonChangeableResult?.gdp_latest_date)}`}
                />

                <h3 className="pt-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
                  B) ISM Manufacturing PMI (MoM)
                </h3>
                <MetricRow
                  label="ISM Manufacturing PMI"
                  value={formatNumber(nonChangeableResult?.pmi_value, 1)}
                  direction={directionFromText(nonChangeableResult?.pmi_trend)}
                  detail={
                    nonChangeableResult?.pmi_previous_value != null
                      ? `Value: ${formatNumber(nonChangeableResult?.pmi_value, 1)} | Previous: ${formatNumber(nonChangeableResult?.pmi_previous_value, 1)} | Delta: ${formatNumber(nonChangeableResult?.pmi_delta_value, 1)} | Date: ${formatDateLabel(nonChangeableResult?.pmi_latest_date)}`
                      : `Value: ${formatNumber(nonChangeableResult?.pmi_value, 1)} | Compared to previous month: ${directionLabel(directionFromText(nonChangeableResult?.pmi_trend))} | Date: ${formatDateLabel(nonChangeableResult?.pmi_latest_date)}`
                  }
                />
              </SectionCard>
            </div>

            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <SectionCard number={6} title="Money Supply" note="Non-changeable with weekly and daily">
                <MetricRow
                  label="M2 (MoM)"
                  value={toTitleCase(nonChangeableResult?.m2_trend)}
                  direction={directionFromText(nonChangeableResult?.m2_trend)}
                  detail={`Change: ${formatPercent(nonChangeableResult?.m2_change)}`}
                />
              </SectionCard>

              <SectionCard number={7} title="Jobs Data" note="Non-changeable with weekly and daily">
                <MetricRow
                  label="Unemployment Rate (MoM)"
                  value={formatPercent(nonChangeableResult?.unemployment_rate, 2, false)}
                  direction={directionFromText(nonChangeableResult?.unemployment_trend_mom ?? nonChangeableResult?.unemployment_trend)}
                />
                <MetricRow
                  label="3-Month Avg Unemployment Rate"
                  value={formatPercent(nonChangeableResult?.unemployment_3m_avg, 2, false)}
                  direction={directionFromText(nonChangeableResult?.unemployment_trend_3m)}
                />
              </SectionCard>
            </div>

            <SectionCard number={8} title="Federal Reserve Signals" note="Non-changeable with weekly and daily">
              <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                <MetricRow
                  label="FED Rate"
                  value={formatPercent(nonChangeableResult?.fed_funds_rate, 2, false)}
                  direction={directionFromText(nonChangeableResult?.fed_rate_trend)}
                  detail={nonChangeableResult?.fed_rate_stance ? `State: ${toTitleCase(nonChangeableResult.fed_rate_stance)}` : undefined}
                />
                <MetricRow
                  label="FED Tone"
                  value={toTitleCase(nonChangeableResult?.fed_tone)}
                  direction={directionFromText(nonChangeableResult?.fed_tone)}
                />
                <MetricRow
                  label="FED Balance Sheet (MoM)"
                  value={toTitleCase(nonChangeableResult?.fed_balance_sheet_trend)}
                  direction={directionFromText(nonChangeableResult?.fed_balance_sheet_trend)}
                  detail="State: Expanding / Neutral / Contracting"
                />
              </div>
            </SectionCard>

            <SectionCard number={9} title="Liquidity and Bonds" note="Non-changeable with weekly and daily">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">A) Treasury 10Y - 2Y (Past 3 months)</h3>
              <div className="overflow-x-auto rounded-lg border border-gray-800">
                <table className="min-w-full text-left text-sm">
                  <thead className="bg-gray-950/70 text-xs uppercase tracking-wide text-gray-400">
                    <tr>
                      <th className="px-3 py-2">Date</th>
                      <th className="px-3 py-2">10Y (A)</th>
                      <th className="px-3 py-2">2Y (B)</th>
                      <th className="px-3 py-2">Spread (+/-)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800">
                    {monthlyYieldRows.map((row) => (
                      <tr key={row.date}>
                        <td className="px-3 py-2 text-gray-200">{row.date}</td>
                        <td className="px-3 py-2 text-gray-100">{formatPercent(row.yield_10y, 2, false)}</td>
                        <td className="px-3 py-2 text-gray-100">{formatPercent(row.yield_2y, 2, false)}</td>
                        <td className="px-3 py-2 text-gray-200">{formatPercent(row.spread, 2)}</td>
                      </tr>
                    ))}
                    <tr className="bg-blue-500/10">
                      <td className="px-3 py-2 text-blue-100">Current data ({new Intl.DateTimeFormat("en-CA").format(new Date())})</td>
                      <td className="px-3 py-2 text-blue-100">{formatPercent(result.ten_year_yield, 2, false)}</td>
                      <td className="px-3 py-2 text-blue-100">{formatPercent(result.two_year_yield, 2, false)}</td>
                      <td className="px-3 py-2 text-blue-100">{formatPercent(result.yield_curve_spread, 2)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-gray-400">
                3-Month Spread Avg: <span className="font-semibold text-gray-100">{formatPercent(spreadAverage3m, 2)}</span>{" "}
                <span className={directionClass(directionFromNumber(nonChangeableResult?.yield_spread_delta_3m))}>
                  ({directionLabel(directionFromNumber(nonChangeableResult?.yield_spread_delta_3m))})
                </span>
              </p>

              <h3 className="pt-2 text-xs font-semibold uppercase tracking-wide text-gray-400">B) Treasury 10Y - 2Y (Yield Curve)</h3>
              <p className="text-xs text-gray-500">
                Condition: A &gt; B = Steepening | A &lt; B = Inversion | A = B = Neutral
              </p>
              <div className="space-y-2">
                {monthlyYieldRows.map((row) => (
                  <MetricRow
                    key={`${row.date}-condition`}
                    label={row.date}
                    value={spreadCondition(row.spread)}
                    direction={directionFromText(spreadCondition(row.spread))}
                  />
                ))}
                <MetricRow
                  label={`Current data (${new Intl.DateTimeFormat("en-CA").format(new Date())})`}
                  value={spreadCondition(result.yield_curve_spread)}
                  direction={directionFromText(spreadCondition(result.yield_curve_spread))}
                />
              </div>

              <h3 className="pt-2 text-xs font-semibold uppercase tracking-wide text-gray-400">C) MOVE (Monthly)</h3>
              <MetricRow
                label="MOVE"
                value={formatNumber(nonChangeableResult?.move_index_value, 2)}
                direction={directionFromNumber(nonChangeableResult?.move_index_change)}
                detail={`Change: ${formatPercent(nonChangeableResult?.move_index_change, 2)}`}
              />
            </SectionCard>

            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <SectionCard
                number={10}
                title="Inflation Metrics-2"
                note="Changeable with monthly, weekly and daily"
              >
                <MetricRow
                  label="WTI"
                  value={formatPrice(result.oil_price, 2)}
                  direction={directionFromNumber(result.oil_change)}
                  detail={`Change: ${formatPercent(result.oil_change, 2)}`}
                />
                <MetricRow
                  label="Natural Gas"
                  value={formatPrice(result.natgas_price, 3)}
                  direction={directionFromNumber(result.natgas_change)}
                  detail={`Change: ${formatPercent(result.natgas_change, 2)}`}
                />
              </SectionCard>

              <SectionCard number={11} title="US Dollar (DXY)" note="Changeable with monthly, weekly and daily">
                <MetricRow
                  label="DXY"
                  value={formatNumber(result.dxy_value, 2)}
                  direction={
                    result.dxy_change != null
                      ? directionFromNumber(result.dxy_change)
                      : directionFromNumber(result.dxy_change_7d)
                  }
                  detail={`Change: ${
                    result.dxy_change != null
                      ? formatPercent(result.dxy_change, 2)
                      : formatPercent(result.dxy_change_7d, 2)
                  }`}
                />
                <MetricRow
                  label="NQEM / EEM"
                  value={formatPrice(result.eem_price, 2)}
                  direction={directionFromNumber(result.eem_change)}
                  detail={`Change: ${formatPercent(result.eem_change, 2)}`}
                />
              </SectionCard>
            </div>

            <SectionCard
              number={12}
              title="Global Risk Sentiment"
              note="Changeable with monthly, weekly and daily"
            >
              <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                <MetricRow
                  label="S&P 500"
                  value={formatNumber(result.sp500_price, 0)}
                  direction={directionFromNumber(result.sp500_change)}
                  detail={`Change: ${formatPercent(result.sp500_change, 2)}`}
                />
                <MetricRow
                  label="Gold"
                  value={formatPrice(result.gold_price, 2)}
                  direction={directionFromNumber(result.gold_change)}
                  detail={
                    result.gold_change != null && Number.isFinite(result.gold_change)
                      ? `Change: ${formatPercent(result.gold_change, 2)}`
                      : `Change: N/A (${result.gold_source ? result.gold_source : "no overlay"})`
                  }
                />
                <MetricRow
                  label="VIX"
                  value={formatNumber(result.vix, 2)}
                  direction={directionFromNumber(result.vix_change)}
                  detail={`Change: ${formatPercent(result.vix_change, 2)}`}
                />
              </div>
            </SectionCard>

            <SectionCard
              number={13}
              title="Bitcoin Market Structure"
              note="Changeable with monthly, weekly and daily"
            >
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <MetricRow
                  label="BTC"
                  value={formatPrice(result.btc_price, 0)}
                  direction={btcTfPct != null ? directionFromNumber(btcTfPct) : directionFromArrow(result.btc_market_arrow)}
                  detail={`Change (${timeframe === "current" ? "~24h" : timeframe === "week" ? "~7d" : "~1M"}): ${formatPercent(btcTfPct, 2)}`}
                />
                <MetricRow
                  label="BTC.D"
                  value={formatPercent(result.btc_dominance, 2, false)}
                  direction={directionFromNumber(result.btc_dominance_change)}
                  detail={
                    result.btc_dominance_change != null && Number.isFinite(result.btc_dominance_change)
                      ? `Change (vs prior saved snapshot): ${formatPercent(result.btc_dominance_change, 2)}`
                      : "Change: N/A — needs a second stored analysis, or dominance came from a snapshot without history."
                  }
                />
              </div>
            </SectionCard>
          </div>
        ) : null}
      </div>
    </main>
  )
}
